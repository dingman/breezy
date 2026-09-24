# AUD-10 — Review record (Round 1)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 9e7b9d5c2a4775aa34339acf541e833b70afa2593e6e64b090ab6f6d0201f3a8 (filled by coordinator at save time; plan may have been unchanged since review)
- Round: 1 · Reviewer: code-architect
- Total: 69/100 · Readiness: NOT READY

## Claims verified

| Ref | Plan claim | Result |
|---|---|---|
| §3.2 "`load_family_manifest` validates `stations` as a non-empty list of strings (:289-297) and carries it onto `FamilyManifest.stations` (:183, :345)" | CONFIRMED exactly — family_manifest.py:289-297, dataclass field at :183, construction at :345. |
| §3.3 "`composition.py:448` and `:553` iterate `SUPPORTED_STATIONS`" | CONFIRMED at :448 (`build_current_rung_hold_strategies`) and :565 (`build_continuous_rung_hold_strategies` — plan says :553, drift of 12 lines; the builder starts at :488, plan says :486). |
| §3.3 "everything else IS threaded from the manifest; stations are the one hole" | CONFIRMED in shape (`required_fee_coefficient`, `exit_manifest` are threaded) — but INCOMPLETE: see P1. |
| §6 "`resolved[station]` remains total" | CONFIRMED — `buckets` is keyed by all `SUPPORTED_STATIONS` (composition.py:318-320), so narrowing the builder loop leaves `resolved[station]` total. |
| §9 "if *all* declared stations resolve zero, `NoTradableInstrumentsError` fires as today" | REFUTED — see P2. |
| §6 "`MIN_NON_EXCLUDED_N = 30` (`runtime/roi_bound.py:100,190`)" | REFUTED as cited: the symbol is at `src/breezy/settlement/roi_bound.py:100`. Name, value and line match; the package does not. |
| §6 "Nautilus has no notion of a promotable family revision; the layer is already Breezy-owned" | CONFIRMED in substance — `persistence/family_manifest.py` is the whole layer and Nautilus' composition surface is `Trader.add_strategy` uniqueness on `f"{strategy_id}-{order_id_tag}"`, which `_station_config` (composition.py:387-421) already uses per station. |
| §5 "`load_family_manifest`'s refusals stay exactly as strict" | CONFIRMED: `UnregisteredFamilyManifestError` (:151, raised :255-258), `UnpinnedBoundaryArtefactError` (:155, raised :265-269), `UnpinnedDensityArtefactError` (:159, raised :283-287). C7's design (a draft proposal is refused without `allow_draft=True`) is sound against this source. |

## Defects

**P1 (MATERIAL) — the specified diff does not close REG-1, and C4 is unattainable as written.**
§6 changes exactly two loops (`composition.py:448`, `:553`). `resolve_station_instrument_ids`
(composition.py:297-372) is itself hard-gated on the module constant at three further points:
`buckets = {station: {} for station in SUPPORTED_STATIONS}` (:318-320); `if station not in
SUPPORTED_STATIONS: continue` (:328); and `_zero_instruments_message` (:381) formats its per-station
counts by iterating `SUPPORTED_STATIONS`. Acceptance criterion C4 ("`SUPPORTED_STATIONS` appears
**zero** times in a station-iteration position in `composition.py`") therefore cannot be satisfied by
the plan's own change list, and the refusal message will report counts for stations the manifest
deliberately excluded — the exact "reads as governed but is not" shape REG-1 is.
REQUIRED: enumerate all five sites in §6, decide each (narrow vs. deliberately leave as the
allow-list gate, with the reason), and restate C4 against that decision.

**P2 (MATERIAL) — §9's safety claim is refuted by the source; the residual is a silent
no-strategy boot.** §9 says "if *all* declared stations resolve zero, `NoTradableInstrumentsError`
fires as today". The guard is `all(len(ids) == 0 for ids in resolved.values())` at composition.py:444
and :544, evaluated over buckets keyed by **all four** `SUPPORTED_STATIONS`. Under a narrowed
manifest, a day on which both declared stations resolve zero instruments but an *undeclared* station
resolved some does NOT raise: the guard passes, the narrowed loop skips both declared stations with
a WARN, and the builder returns an empty tuple — the node boots with zero strategies and no refusal.
That is a new silent-halt class introduced by 10a, in a repo whose audit is about silent halts.
REQUIRED: narrow the zero-guard (and/or the bucket keys and the `:328` gate) to the composable set,
and add a RED test for exactly this case: 2-station manifest, both zero, a third station non-zero →
`NoTradableInstrumentsError`.

**P3 (MATERIAL) — `src/breezy/analysis/promotion_criteria.py` breaks `lint-imports`.**
Same defect as AUD-09 N1: `breezy.analysis` does not exist and the layers contract is
`exhaustive = true` (pyproject.toml:92), so the package fails the contract that §7 step 6 runs as a
gate. Because both plans populate the same new package with different downward dependencies, the
layer position must be decided once and consistently.
REQUIRED: specify the layers amendment and the position; note that p1's correction (roi_bound is in
`settlement`, the bottom layer) makes the position easier, not harder.

**p1 (MINOR)** `MIN_NON_EXCLUDED_N` cited as `runtime/roi_bound.py:100,190`; it is
`settlement/roi_bound.py:100`. Materially harmless (it relaxes the layering constraint) but it is a
wrong path in a table whose whole point is that nothing is hard-coded.
**p2 (MINOR)** There is no manifest **writer**. `family_manifest.py` exposes only
`load_family_manifest` (:211-354) and the key sets `_REQUIRED_KEYS` (:96-111) / `_OPTIONAL_KEYS`
(:125). §6b's generator must serialise a candidate manifest; if it hand-rolls the JSON, its key set
drifts from `_REQUIRED_KEYS` — the parallel-architecture risk this plan otherwise avoids well.
C7 catches a refusal, not optional-key drift. REQUIRED: colocate a serialiser with the loader and
add a round-trip test (`load_family_manifest(write(m), allow_draft=True) == m`).
**p3 (MINOR)** §9's idempotency rule — "a second run on unchanged inputs produces a byte-identical
proposal directory name collision, which is refused rather than overwritten" — does not hold: §6b
names the directory `derived/promotion/proposals/<utc-stamp>/`, which never collides across runs.
Either key the directory on a content hash of the inputs (then the claim is true and testable), or
drop it.
**p4 (MINOR)** C8 ("first real run emits `NO_PROPOSAL`") is an expectation, not a test — a
`PROPOSAL` would not fail acceptance. The plan concedes this in §13.
**p5 (MINOR)** §3.3/§6 line drift: `build_continuous_rung_hold_strategies` starts at :488 and its
loop is at :565 (plan cites :486/:553).

## Strengths (credited)
The brief asked whether 10b builds parallel architecture beside the family-manifest loader: it does
not, and deliberately so. The proposal IS the existing manifest schema emitted as a draft, and the
loader's own `allow_draft=False` refusal is used as the safety property rather than routed around
(C7) — verified against family_manifest.py:151-166, 255-287. Arming, `sending_family_id`, the
operator caps, PREREG §3/§5/§9, the fee-coefficient pins, and the mutual-exclusion contract test are
all explicitly untouched, and each exclusion carries a reason. Every criterion in the §6 table cites
a written source, and the forecast-family transfer problem is surfaced as a blocker rather than
decided.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 13 | Addresses REG-1 and the unenforced criteria and updates rather than duplicates the PROGRESS row; but as specified 10a does not actually close REG-1 (P1) and introduces a new hole (P2). |
| Technical correctness and evidence grounding | 20 | 13 | Manifest claims confirmed exactly; the REG-1 diagnosis is right as far as it goes. Lost on one refuted safety claim (P2), one refuted citation (p1), and the missed constant sites (P1). |
| Implementation specificity and feasibility | 15 | 10 | 10a is specified down to the call reorder; three unaddressed `SUPPORTED_STATIONS` sites, the missing serialiser and the undecided layer leave real work undefined. |
| Acceptance criteria and validation quality | 20 | 13 | C1-C3, C6, C7, C9 objective, with a golden byte-identity pin and L-33 mutation evidence. C4 unattainable, C8 not a test, nothing covers the empty-composable-set boot or manifest-key drift. |
| Autonomous operation, failure handling, recovery | 15 | 11 | Three hard refusals, contradiction ordering with C-KILL first, read-only posture, clean rollback. p3's idempotency claim is wrong; no alerting beyond the host unit's failed state. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Honest zero-ROI statement, correctness benefit named as such, blockers named not decided, abandonment criterion stated. |
| **Total** | **100** | **69** | |

## Required changes to reach 100
1. Enumerate and dispose of all five `SUPPORTED_STATIONS` sites in `composition.py`; restate C4 (P1).
2. Narrow the `NoTradableInstrumentsError` guard to the composable set and RED-test the
   two-zero-declared/one-nonzero-undeclared case (P2).
3. Specify the `[tool.importlinter]` layers amendment for `breezy.analysis`, consistently with
   AUD-09 (P3).
4. Correct the `roi_bound` path (p1); colocate a round-trip-tested manifest serialiser (p2); fix or
   drop the directory-collision idempotency claim (p3); make C8 a test with a defined pass condition
   for both outcomes (p4); correct the composition line refs (p5).

## Blockers
- **BLOCKER (strategy lead) — real and score-capping for 10b.** R5-7/R5-8 in
  `FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152` were written for `pm_us_crh_fc_v1` under a
  programme ruled terminally CLOSED. Whether they transfer to a `continuous_rung_hold` family, and
  what champion/challenger means when the champion's admissible n = 0, is a ruling. The plan's
  `SOURCE=FORECAST_FAMILY_R5` tagging is the right mitigation and keeps the BUILD executable, but
  10b cannot be judged *correct* (as opposed to *faithfully transcribed*) until the ruling exists.
- **BLOCKER (strategy lead)** — whether a MECHANISM_ONLY replay row may feed any criterion.
  `C-VALIDITY`'s default (no) is the conservative choice and is correctly surfaced, not decided.
- **BLOCKER (operator)** — arming, live enablement, the two caps. Correctly named and untouched;
  no code in this item reads, writes or proposes a value for them. No violation found.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool (it self-labelled as code-architect)._
