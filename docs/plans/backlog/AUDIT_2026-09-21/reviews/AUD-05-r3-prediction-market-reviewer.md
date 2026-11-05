# AUD-05 — Round 3 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
SHA256: 1075f52e1c7a551a668fc7b3739f1b280839fed11979084e7af7fbcb12488662
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)

## Round-2 defect disposition verification

All round-2 dispositions attributed to this lens are genuinely closed in the plan body:

- D-A re-pointed to `build_stratum_v2` (not `combine_station_day`): CONFIRMED against source.
  `build_stratum_v2` def at `current_rung_hold_v2.py:405`, body computes `n`(`:424`),
  `k = sum(1 for row in rows if row.held)`(`:425`), `mean_ask`(`:426`),
  `pi = mean(break_even_row(...))`(`:427`), Wilson(`:428`); `StratumV2` fields (`:386-397`) are
  exactly `label, n, k, mean_ask, pi, wilson_lower, wilson_upper` — no variance field, matching the
  plan's claim exactly. `combine_station_day` def at `:298`, `signs` at `:329`, `qs` at `:330`,
  diagonal at `:341`, cross term at `:344` — all confirmed byte-accurate.
- `pi := mean(BE_i)` ruling vs. the rejected `mean(q_i)` alternative: CONFIRMED sound. `StratumRow`'s
  docstring (`:99-105`, re-read in full) states `entry_ask`/`fee` are the leg's own and `held` is the
  per-side truth with "no further inversion of its own"; `_cell_probability` (`:225-227`) confirms
  `q_i = BE_i` for YES, `1 − BE_i` for NO. Under H0 a NO leg's `E[held_i] = 1 − q_i = BE_i`, so
  `pi = mean(BE_i)` is exactly the null `k/n` is compared against — the rejection of `mean(q_i)` as
  inverted for NO rows is correct.
- Unequal-qty characterisation test, orphan re-accumulation guard: both present as claimed in §7.

No round-2 disposition is misrepresented.

## Fresh review of the full revision — MATERIAL, new this round

**MATERIAL — side-partitioning the station/ask-band strata changes a component of the sequential
test's KILL decision that PREREG v3 §7 registers as UNCHANGED, and this plan neither surfaces that
nor obtains a ruling for it.**

File: AUD-05 §6 D-A ("What is genuinely not side-safe is POOLING, and that is the change").

Evidence, read from source, not asserted:

1. `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §7 "UNCHANGED from PREREG v3" lists,
   verbatim: **"Strata: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)"** —
   registered as byte-identical to PREREG v3, not merely referenced.
2. `station_strata`/`ask_band_strata` (built via `build_stratum_v2` at `family_tally_v2.py:498` and
   `:511`) are NOT cosmetic diagnostics. `any_cell_dead = any(s.cell_dead for s in (*station_strata,
   *ask_band_strata))` (`family_tally_v2.py:655`) feeds directly into `look_verdict(...,
   cell_dead=any_cell_dead, ...)` (`:748`), and `look_verdict`'s own docstring
   (`current_rung_hold_v2.py:449-451`) states `KILL <=> S <= b_fut OR cell_dead OR structural_fired`.
   So a station/ask-band stratum's `cell_dead` is a live KILL trigger on the REGISTERED sequential
   test — not, as the plan's `StratumV2` docstring quote implies ("no sequential monitoring here"),
   an inert side channel. (`pooled`, by contrast, IS reporting-only — I confirmed its only other use
   is `_fmt_stratum_row` in the rendered report — so partitioning `pooled` by side is low-risk; the
   material risk is confined to `station_strata`/`ask_band_strata`.)
3. D-A's proposed fix (§6, "the change is: drop the blanket side refusal, and partition every
   stratum by side... built at the three call sites `family_tally_v2.py:498`, `:511` and `:645`")
   restructures `station_strata`/`ask_band_strata` from "one stratum per station/ask-band, covering
   every row regardless of side" (today's registered, frozen shape) into "one stratum per
   (station|ask-band) × side" (a NEW partition, e.g. `station:KSFO|no` as a distinct entity that does
   not exist today). This changes which cells can independently fire `cell_dead`, and therefore
   changes the KILL rate's operating characteristics relative to the registered §7 shape — exactly
   the class of change PREREG semantics are supposed to gate, per this backlog's own binding
   constraint ("PREREG semantics only via ruling").

The plan's own claim in §6 — "This keeps D-A a field- and call-site-level change that invents no
statistic, and leaves the registered sequential statistic (`combine_station_day` → `score_combined`)
byte-untouched" — is true only for the pooled sequential monitor's own `S`/`I` computation. It is not
true for the KILL decision as a whole, because `cell_dead` (fed by the now-repartitioned
`station_strata`/`ask_band_strata`) is one of `look_verdict`'s three KILL disjuncts. The plan
conflates "the statistic `combine_station_day` computes" with "everything that can trigger KILL",
and only the former is proven unchanged (by the byte-identity floor and the unequal-qty test). The
latter — the thing §7 actually registers as frozen — is restructured by this item without a ruling.

Why this matters in dollar/decision terms (the pm lens): `cell_dead` firing is a KILL, which
terminates the sequential monitor for that family. Silently changing what can fire it changes when
the live family's admissible-evidence collection stops relative to what was registered — a
false-KILL introduced by an unregistered side-partition would prematurely end the very tally this
item exists to restore, and a false-negative (a cell that SHOULD go dead under the registered shape
but does not under the new partition) would let a genuinely dead cell keep contributing admissible
looks. Either direction is a silent change to the registered stopping rule's operating
characteristics, which is squarely inside L-34's "class-C PREREG semantics change" territory — the
same authority this plan already invokes for BLOCKER-1 (the `trial_id_prefix` collision).

Failure: the tally ships, cell_dead-driven KILLs (or non-KILLs) occur under a stratum partition the
registration never described, and nobody can say whether the family's admissible n reflects the
registered stopping rule or this plan's unregistered generalisation of it — corrupting the
evidentiary basis for every future look on this family, silently, exactly the WP-R1-adjacent failure
class this backlog exists to close elsewhere.

Fix: either (a) obtain an explicit strategy-lead/PREREG ruling that side-partitioned station/ask-band
`cell_dead` strata are within the §7 "station (cell_dead), ask-band (cell_dead)" registration (the
amendment is silent on how mixed-side rows interact with these two diagnostic strata, so this is a
genuine gap in the registration, not merely an implementation question), stated as a named BLOCKER in
§12 alongside BLOCKER-1/2 — this is the correct disposition per the brief's rule that a
PREREG/operator ruling is a BLOCKER, not a deduction the plan text alone can fix; or (b) restrict D-A
to the `pooled` stratum only (which is reporting-only and provably does not feed `look_verdict`), and
leave `station_strata`/`ask_band_strata` refusing mixed-side rows exactly as today, deferring their
side-awareness to the ruling in (a). Option (b) is smaller and does not require blocking D-A's core
fix (unblocking the tally on a NO fill) on a ruling, since the tally's fatal `ValueError` is reached
via `build_stratum_v2("pooled", ...)` first (per the plan's own execution-order note) — a `pooled`-
only fix already clears the measured D-A failure.

This is a genuinely new finding for round 3: neither round-1 nor round-2 reviewers (mle or pm) raised
it, and the plan's own self-scores do not name it either.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **16** — G-04 fully covered; D-D/D-F/D-E correctly surfaced.
  −4 for the material defect above: the plan does not surface that its own fix touches a registered,
  frozen element of PREREG v3 §7.
- Technical correctness and evidence grounding (20): **13** — every cited line number and formula
  re-verified accurate; the `pi = mean(BE_i)` derivation is genuinely correct math. −7 for the
  material defect: the plan's central correctness claim ("leaves the registered sequential statistic
  byte-untouched") is incomplete in a way that matters for a money-moving admissibility gate.
- Implementation specificity and feasibility (15): **10** — call sites, formula, alert latch, field
  lists all named. −5: the fix as specified cannot be implemented today without either the missing
  ruling or the narrower `pooled`-only scoping in the required fix above.
- Acceptance criteria and validation quality (20): **15** — AC#5's three-way invariance proof and
  AC#11's ruling-honoring test are strong for what they cover. −5: no AC asserts that
  `station_strata`/`ask_band_strata`'s KILL-triggering behaviour is unchanged or ruled-on — the
  byte-identity floor covers only the all-YES case, which by construction never exercises the new
  partition's KILL divergence.
- Autonomous operation, failure handling, recovery (15): **13** — D-F's latched alert and the orphan
  re-accumulation guard are sound and unaffected by the above. −2, matching round 2's mark, for the
  timer-firing dependency both signals still share.
- Portfolio objective alignment, scope and dependencies (10): **10** — §11's chain, numeric baseline
  and falsifier are concrete. Per the brief's rule, disposition #6 (round 2, no named defect) is
  resolved: I find no separate defect in §11 itself, so full marks are awarded here, matching the
  round-2 pm score. (The material defect above is scored under "technical correctness" and
  "completeness", not here, since it is not a portfolio-alignment defect.)

**Total: 77/100**

## Required changes to reach 100

1. Either obtain and record a strategy-lead/PREREG ruling authorizing side-partitioned
   `station_strata`/`ask_band_strata` as within PREREG v3 §7's "station (cell_dead), ask-band
   (cell_dead)" registration (named as a new BLOCKER), or narrow D-A's stratum-partitioning change to
   the `pooled` label only (reporting-only, provably inert to `look_verdict`) and leave
   `station_strata`/`ask_band_strata` refusing mixed-side rows until that ruling exists.
2. Add an acceptance criterion/test asserting that the set of `cell_dead`-eligible strata that can
   fire KILL on an all-YES corpus is unchanged by this item (the existing byte-identity floor does
   not exercise this because it never has a NO row).

## Blockers

**New BLOCKER (this round), named per the brief's rule that a PREREG/operator ruling is a blocker,
not a deduction:** side-partitioning `station_strata`/`ask_band_strata` — which feed the REGISTERED
sequential test's `cell_dead` KILL trigger — is not described by PREREG v3 §7's "UNCHANGED" strata
list, and this plan does not obtain a ruling for it. No plan-text change alone resolves this; either
a strategy-lead ruling or a narrower (pooled-only) scoping is required.

BLOCKER-1 and BLOCKER-2 (from the plan itself) remain open and are not resolvable by any reviewer, as
stated in the plan's own §12.
