# AUD-10 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: fc8ab3a49c765a4cc724cc3983a5ab107311422e0a9eb9b58b9e9445de027e52 (filled by coordinator at save time)
- Round: 2 · Reviewer: architect (code-architect lens)
- Total: 82/100 · Readiness: NOT READY

## Round-1 dispositions verified against the plan body

| R1 defect | Claimed | Verified in body? |
|---|---|---|
| P1 — the two-loop change list does not close REG-1; C4 unattainable | ACCEPTED | **FIXED, and the enumeration is exact.** I re-derived the occurrences: `composition.py:45` (import), `:319` (buckets), `:328` (filter), `:381` (message), `:448`, `:565` — six, exactly the plan's table, no seventh site. The dispositions are also *feasible*, which the plan asserts but does not prove: `resolve_station_instrument_ids(catalog_root, today_by_station)` already takes the mapping as a parameter (`:297-300`), and `_zero_instruments_message(resolved, today_by_station)` already takes both (`:375-378`), so every narrowing is a local edit with no new parameter. C4 (`grep -c … == 0`) is attainable after the `:45` removal. The two-layer allow-list argument also holds: `_station_config` (`:387-421`) constructs `CurrentRungHoldConfig` for **both** builders and `__post_init__` raises `UnsupportedStationError` for any station outside the tuple (`config.py:245-252`). |
| P2 — narrowed manifest can boot with zero strategies | ACCEPTED | **GENUINELY FIXED, and it was the right finding.** Verified at source: the guard is `all(len(ids) == 0 for ids in resolved.values())` at `:444` and `:544`, over buckets keyed at `:319`. Narrowing `:319` to `today_by_station` makes the guard fire on the two-declared-zero / one-undeclared-non-zero shape without inventing a new guard. C5/C6 and §7 step 3 test exactly that, for both builders. |
| P3 — `breezy.analysis` breaks `lint-imports` | ACCEPTED | **PARTIALLY FIXED.** Layer position decided and quoted; I diffed §6's block against AUD-09 §6 — layers list, both contracts and the allowed-import sentence are equivalent, and C10/B10 are the same criterion as claimed. But the literal contract does not pass — see 10-1. |
| p1 `roi_bound` path · p2 serialiser · p3 idempotency · p5 line drift | ACCEPTED | All fixed in body: `settlement/roi_bound.py:100`; `dump_/write_family_manifest` colocated and built from `_REQUIRED_KEYS \| _OPTIONAL_KEYS` with a round-trip test (C11); content-hashed proposal directories with `INPUTS.json` as pre-image (C12); `:565`/`:488` corrected — both confirmed against source. |
| p4 C8 not a test | ACCEPTED | Fixed: C8 now defines a pass condition for both outcomes and fails any third shape. |

The rejection of tba's "narrow C4's wording" option is correctly reasoned: leaving `:319` wide is
exactly what makes the guard unsound, so the stricter remedy was the only sound one.

## Defects found in revision 2

**10-1 (MATERIAL, NEW — identical to AUD-09 09-1) — the quoted `pyproject.toml` contract cannot pass,
so C10 is unattainable as written.**
`ForbiddenContract.allow_indirect_imports` defaults to **False**
(`.venv/.../importlinter/contracts/forbidden.py:72`), and a false value routes to
`graph.find_shortest_chains(...)` at `:139-143` — indirect chains are violations. The plan's second
contract omits the flag while §6 states `analysis` may import `strategy`, `runtime`, `adapters`,
`ingest`; `breezy.strategy.current_rung_hold.config` imports `nautilus_trader` directly at
`config.py:59-60`, and that module is where `SUPPORTED_STATIONS` (`:76`) — the cited reason for the
layer position — lives. `promotion_criteria.py` additionally needs `persistence.family_manifest`,
whose `FamilyManifest` surface is Nautilus-free, but the `strategy` edge alone breaks the contract.
REQUIRED: set `allow_indirect_imports = true` on that contract with the rationale the `.com` adapter
contract already records (`pyproject.toml:116-121`), or re-source `SUPPORTED_STATIONS` from a
Nautilus-free module. Because C10 == B10, the change must be made identically in AUD-09 §6.

**10-2 (MATERIAL) — H2 is declared "DECLINED" in three files while `C-STATIONS` reads the declined
artefact.**
§6b: "AUD-10 does **not** read `station_candidates.jsonl`" — and, in the same paragraph and again in
the criteria table, "the count of AUD-08b station candidates is **recorded in `criteria.json`** under
`EXPANSION_REQUIRES_RULING`". The count cannot be recorded without reading the register. So the
hand-off is not declined, it is *undeclared*: there is no reader, no `schema_version` check, no
`UnknownStationCandidateSchemaError` behaviour, and no missing-file behaviour (AUD-09's H1 specifies
all three for its own read, and AUD-10b's own §9 rule — "input missing or schema-unknown → refuse with
the path and the version seen" — would then make a missing register *refuse a promotion proposal*,
which is absurd and surely unintended). AUD-08 §6b repeats the same contradictory sentence; AUD-09 §6a
states the clean form. So the three files are **not** consistent on H2.
REQUIRED: make `C-STATIONS` a pure subset predicate over the proposal's own stations and delete the
candidate-count clause from AUD-10 and AUD-08 — or specify the read as a real, bounded hand-off
(reader, unknown-version rule, missing-register = WARN + count 0, never a refusal) in all three files
and stop describing H2 as declined. Either is defensible; the current text is both at once.

**10-3 (MATERIAL) — no input artefact is identified per predicate, and `C-PAIRED` has no producer.**
§6b lists inputs collectively ("replay_results.jsonl, the live tally artefacts, the current
`deploy/families/<sending>.json`, the KILL-clock state") but never binds a predicate to an artefact.
That matters most for `C-PAIRED`: "challenger vs champion compared paired on the same post-`fit_date`
station-days". The champion's admissible live n = 0 (§4, PROGRESS.md:32), so the only possible source
is replay rows — and AUD-09b, as specified, replays only one family (its §6b passes no family to the
driver, and `current_rung_hold_paper_replay.py`'s parser has no family/manifest argument, verified at
`:1076-1113`). There is therefore no path by which challenger rows can exist, so `C-PAIRED` can only
ever evaluate false-for-lack-of-data, and C7's "passing fixture" for it will be synthetic by
construction — a criterion that can be unit-tested but never satisfied in production. The plan's own
§11 argument (a mechanical champion/challenger pairing is the control on this repo's most expensive
recurring error) is undercut by that.
REQUIRED: state, per predicate, which artefact supplies each input; and state explicitly how a
challenger family's replay rows come into existence (the AUD-09b change named in 09-2) or that
`C-PAIRED` is inert until it does — recorded as a dependency, not left implicit.

**c1 (MINOR) — the narrowing's effect on non-`app` callers is not stated.**
§6's L-2 line analyses only the live `pm_us_crh_v4` path. `resolve_station_instrument_ids` and both
builders have other callers (tests; the `:328` allow-list filter disappears entirely once
`SUPPORTED_STATIONS` leaves the module), so any caller passing a `today_by_station` that is not a
subset of the allow-list changes behaviour — now caught downstream by `UnsupportedStationError` in
`_station_config` rather than silently filtered at `:328`. That is the *correct* direction, but it is
a behaviour change the plan does not name. REQUIRED: enumerate the non-`app` callers and state the
expected effect (a one-line addition to the §6 disposition table's `:328` row).

**c2 (MINOR)** `C-ESTIMATOR` leans on `CombinedDraw` / `combine_station_day` signatures the author
concedes (§13) are unread. Since `C-ESTIMATOR` is the one predicate that does real statistics, its
input type should be read and quoted before the plan is called executable.

## Strengths (credited)

10a is now a genuinely complete defect fix: six sites derived by grep, each disposed with a reason,
the guard made correct by narrowing its domain rather than by adding a second guard, a golden
byte-identity pin, and L-33 mutation evidence naming which test must fail for which perturbation. The
P2 finding being promoted to "the most important finding of round 1" and fixed at the root is the
right engineering call. 10b still builds no parallel architecture: the proposal IS the existing
manifest schema emitted as a draft, and `load_family_manifest`'s own `allow_draft=False` refusal is
used as the safety property rather than routed around. The three hard refusals, the content-hash
idempotency, and the four-acts-none-automatable framing of the human gate are all concrete. Both
strategy-lead blockers are retained verbatim and marked score-capping rather than softened.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 10a closes REG-1 completely and closes the hole it would have opened. 10b's criteria set has a predicate with no producer (10-3), and G-07's "promotion is a unit-file commit" half is still only partially addressed — honestly stated. |
| Technical correctness and evidence grounding | 20 | 15 | Every re-opened citation is exact (six sites, `:444`/`:544` guard, `:297-300`/`:375-378` signatures, `settlement/roi_bound.py:100`, manifest refusals). Lost on 10-1 (verified error against import-linter's default) and 10-3 (a criterion whose input cannot exist). |
| Implementation specificity and feasibility | 15 | 12 | 10a is specified to the call reorder and per-site edit and is feasible as written. 10b leaves predicate→artefact binding open, the quoted contract does not run, and C-ESTIMATOR's types are unread. |
| Acceptance criteria and validation quality | 20 | 16 | C1–C9, C11–C13 objective; C4 now attainable; C5/C6 cover the new silent-halt class; C8 is a real two-way test; C12 is a real property. C10 unattainable as written; C7's `C-PAIRED` case is necessarily synthetic. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Three hard refusals, C-KILL-first contradiction ordering, content-hash idempotency, read-only posture, clean rollback. Deducted for the undeclared register read whose missing-file path is governed by a refuse-and-exit rule (10-2), and no alerting independent of the host unit. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Zero-ROI honesty, correctness benefit named as such and not counted as return, blockers kept not softened, abandonment criterion scoped to 10b only, arming/caps/NO-SEND untouched. |
| **Total** | **100** | **82** | |

## Required changes to reach 100
1. Fix the Nautilus forbidden contract identically here and in AUD-09 (10-1).
2. Resolve H2: either drop the candidate-count clause from `C-STATIONS` (and from AUD-08 §6b), or
   specify the register read as a bounded hand-off in all three files (10-2).
3. Bind every predicate to its input artefact, and state how challenger replay rows are produced — or
   record `C-PAIRED` as inert until AUD-09 can replay a non-armed family (10-3).
4. Name the non-`app` callers affected by the `:328` narrowing (c1); read and quote `CombinedDraw` /
   `combine_station_day` before `C-ESTIMATOR` is called executable (c2).

## Blockers
- **BLOCKER (strategy lead) — real and score-capping for 10b, unchanged from round 1.** R5-7/R5-8
  (`FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`) were written for `pm_us_crh_fc_v1` under a
  programme ruled terminally CLOSED. Whether they transfer to a `continuous_rung_hold` family, and what
  champion/challenger means when the champion's admissible n = 0, is a ruling. `SOURCE=FORECAST_
  FAMILY_R5` tagging keeps the build executable, but 10b cannot be judged *correct* — only faithfully
  transcribed — until that ruling exists. Correctly retained, not softened.
- **BLOCKER (strategy lead)** — whether a `MECHANISM_ONLY` row may feed any criterion. `C-VALIDITY`'s
  default (no) is conservative and surfaced, not decided.
- **BLOCKER (operator)** — arming, live enablement, the two reserved caps. Named, untouched; no code
  in this item reads, writes or proposes a value for them. No violation found.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
