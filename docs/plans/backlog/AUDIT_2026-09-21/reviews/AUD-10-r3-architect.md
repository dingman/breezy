# AUD-10 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 18a2e1fab679c80a996e078a777380707f0c0b84f8bc3cae01a09057f29aad6d (filled by coordinator at save time)
- Round: 3 · Reviewer: architect (code-architect lens)
- Total: 87/100 · Readiness: NOT READY

## Round-2 dispositions, verified against the plan body and against source

| R2 defect | Claimed | Verified? |
|---|---|---|
| **10-1 (= 09-1)** — the quoted forbidden contract cannot pass | ACCEPTED | **FIXED and correct.** `allow_indirect_imports` defaults to `False` (`importlinter/contracts/forbidden.py:72`) and only `str(...).lower() == "true"` reaches `_get_direct_chains` (`:131-137`); the `else` branch is `find_shortest_chains` (`:138-143`). The flag with its rationale mirrors the repo's own precedent (`pyproject.toml:116-121`). I diffed §6's layers list and both contracts against AUD-09 §6 — character-equivalent, so C10 == B10 as claimed. The re-sourcing rejection is evidenced and consistent with 10a, which removes `SUPPORTED_STATIONS` from `composition.py:45`. |
| **10-2** — H2 "declined" while `C-STATIONS` reads the register | ACCEPTED | **FIXED, in all three files.** §6b.2 states the decline without residue and records why the bounded-read alternative was rejected (§9's blanket refuse rule would let a missing register refuse a proposal); §6b.3's `C-STATIONS` row is a pure subset predicate whose input column is "the proposal's own draft manifest only" and whose absent-input cell is "n/a"; AUD-08 §6c and AUD-09 §6a carry the identical statement. §9's blanket rule is correctly replaced by the per-predicate column. |
| **10-3** — no input artefact per predicate; `C-PAIRED` has no producer | ACCEPTED IN FULL | **MOSTLY FIXED.** The table gains an **input artefact** and an **absent-input behaviour** column for all eight predicates, **C15** asserts `criteria.json` carries the artefact per row, and `C-PAIRED` is resolved the right way: literal verdict `INERT` (never `false` — the distinction between "the challenger lost" and "no challenger exists" is exactly right), `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, the named blocking change with an owner, a §12 entry mirrored in AUD-09, and **C14** (an `INERT` predicate can never yield `PROPOSAL`). The unasked-for `C-VALIDITY` `params_match` clause (**C16**) closes the other half of the same hazard. **Residual: two of the eight inputs are named by producer, not by artefact — see 10-4.** |
| **c1** — non-`app` callers of the narrowed functions not stated | ACCEPTED | **FIXED and accurate.** I re-opened `tests/unit/test_no_leg_composition_2026_09_14.py`: the three imports are at `:47-49`, `resolve_station_instrument_ids(tmp_path, {"LAX": _DAY})` at `:128`, the builders at `:145`/`:174` — exactly as enumerated, and the mapping is allow-list-shaped, so "effect: none" is correct. The stated direction (a silent `:328` filter becomes a loud `UnsupportedStationError` from `_station_config`, `composition.py:387`) is right, and §7 step 5's instruction never to restore the filter is the correct guard. |
| **c2** — `C-ESTIMATOR` leans on unread signatures | ACCEPTED | **FIXED, and the reading changed the design.** Verified: `combine_station_day(rows: Sequence[StratumRow] \| tuple[StratumRow, ...]) -> CombinedDraw` at `settlement/current_rung_hold_v2.py:298`; `CombinedDraw` at `:196`; `score_combined` at `:348`. The two consequences drawn — `CombinedDraw` carries no station/climate day so pairing is the caller's bookkeeping, and refusals must be caught per-run rather than allowed to abort — are both correct and are real design changes, not restatements. **But the refusal set is under-counted — see c1 below.** |

10a's six-site enumeration re-verified once more against source: import `:45`, buckets `:319`, filter
`:328`, message `:381`, builders `:448`/`:565`, guards `:444`/`:544`, `_zero_instruments_message`
`:375`, `resolve_station_instrument_ids` `:297`, `_station_config` `:387`. Exact, complete, no seventh
site. C4 remains attainable.

## Defects found in revision 3

**10-4 (MATERIAL, NEW) — `C-KILL`'s input artefact is named only by its producing script, has no
path, no key set and no staleness rule, while its absent-input behaviour is "refuse the whole run".**
§6b.3 binds `C-KILL` to "the KILL-clock state written by `scripts/analysis/structural_dead_stop.py`".
That script does write a machine-readable artefact — an atomic six-key JSON to a **caller-supplied**
`--output` (`structural_dead_stop.py:289, 297-326`, with `:189` recording that "the six-key `--output`
contract stays pinned") — so the plan is pointing at something real but never binds it: no path, no
enumeration of which of the six keys the predicate reads, no reader, no `schema_version` rule. H3 got
all seven rows; this input got none, and it is the **only** input whose absence refuses the entire
nightly run, so an unbound path means the generator's steady-state outcome is undetermined. Worse, the
failure mode the plan does not name is the dangerous one: a **stale** KILL-clock JSON (written days
ago, before a clock tripped) parses fine and reads as "not tripped" — silently permissive, which is
precisely what this row's own parenthetical says must not happen ("a promotion with an unknown clock
is the one case where silence must not be permissive"). The same under-binding, at lower stakes,
applies to `C-ESTIMATOR`/`C-N`, whose inputs are named as `family_tally_v2.py` and
`persistence/realized_draws.py` — a script and a module, not artefacts with paths.
REQUIRED: bind `C-KILL` to a literal artefact path, the keys it reads, and a **max-age rule** (stale ⇒
refuse, identically to absent), with a test; and name the live-tally artefact paths for
`C-ESTIMATOR`/`C-N` rather than their producers.

**c1 (MINOR) — "four documented refusals" under-counts the reachable refusals by three.**
§6b.3 and **C15** enumerate four raise sites (`:318-319`, `:320-325`, `:269-273`, `:331-336`). Read at
source, `combine_station_day` reaches `_fold_same_rung_rows`, which raises
`StationDayAdmissionRefusal` at **three further, distinct shapes**: same-rung same-side fills at
differing `entry_ask` (`:276`), at differing `fee` (`:282`), and disagreeing on `held` (`:288`). All
seven inherit `ValueError` (`StationDayAdmissionRefusal(ValueError)` at `:184`), so a base-class catch
handles them — but C15's per-shape enumeration would leave three malformed-input shapes untested, and
the count "four" is the docstring's list, not the code's.
REQUIRED: catch `StationDayAdmissionRefusal`/`ValueError` at the base and restate C15 over all seven
shapes (or state that the base catch is the contract and the four are illustrative).

**c2 (MINOR) — the boot log line asserted in §10 has no acceptance criterion.** §10 requires the boot
log to state "the composed station set **and** the manifest it came from" and claims it as the
cheapest partial repair of G-15(b). Nothing in C1–C16 tests it, and §7 has no step for it. Every other
observable in this plan is pinned. REQUIRED: add a one-line assertion to C3's golden test or a new
criterion.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 10a closes REG-1 completely and closes the zero-strategy boot path it would have opened. 10b now binds six of eight predicates to real inputs; the one that gates the whole run is unbound (10-4), and G-07's "promotion is a unit-file commit" half remains partially addressed — honestly stated. |
| Technical correctness and evidence grounding | 20 | 17 | Every citation I re-opened is exact: the six `SUPPORTED_STATIONS` sites, the `:444`/`:544` guards, `_station_config:387`, `_zero_instruments_message:375/381`, `resolve_station_instrument_ids:297`, `CombinedDraw:196` / `combine_station_day:298` / `score_combined:348`, the c1 test-file lines `:47-49,128,145,174`, `pm_us_crh_v4.json:17` `"0.0695"` vs `config.py:226` `Decimal("0.06")`, and the import-linter default. Deducted for the under-counted refusal set (c1) and the unbound KILL artefact (10-4). |
| Implementation specificity and feasibility | 15 | 12 | 10a is specified to the per-site edit, the call reorder and the mutation evidence — executable as written. 10b leaves the KILL-clock read (path, keys, staleness) for the implementer (10-4), which is the input that decides whether the generator runs at all. |
| Acceptance criteria and validation quality | 20 | 18 | C1–C16 objective; C7's absent-input fixtures, C8's two-way condition, C12's content-hash property, C14's INERT rule and C16's `params_match` refusal are all real tests. Deducted: C15 enumerates four of seven refusals (c1), C-KILL's absent/stale case has no artefact to test against (10-4), and the §10 boot-log observable is unpinned (c2). |
| Autonomous operation, failure handling, recovery | 15 | 13 | Three hard refusals, `C-KILL` evaluated first and disqualifying alone, content-hash idempotency, read-only posture, per-predicate absent-input handling replacing the blanket rule, clean rollback tied to the layers amendment. Deducted for 10-4: a stale clock state is silently permissive, and there is still no alerting independent of the host unit. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; the correctness benefit named as correctness and not counted as return; blockers retained verbatim rather than softened; abandonment criterion scoped to 10b only; arming, the two reserved caps and the NO-SEND path untouched. No defect found. |
| **Total** | **100** | **87** | |

## Required changes to reach 100
1. Bind `C-KILL` to a literal artefact path, its key set, a reader and a **staleness ⇒ refuse** rule,
   with a test; name the live-tally artefact paths for `C-ESTIMATOR`/`C-N` (10-4).
2. Restate C15's refusal handling over all seven reachable shapes, or make the base-class catch the
   stated contract (c1).
3. Pin the §10 boot-log line (composed stations + manifest id) to a criterion (c2).

## Blockers (recorded separately; not scored)
- **Strategy lead — 10b cannot be judged correct without a ruling.** R5-7/R5-8
  (`FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`) were written for `pm_us_crh_fc_v1` under a
  programme ruled terminally CLOSED; whether they transfer to a `continuous_rung_hold` family, and
  what champion/challenger means when the champion's admissible n = 0, is a ruling. The
  `SOURCE=FORECAST_FAMILY_R5` tagging keeps the build executable and the transfer auditable; the
  plan correctly transcribes rather than adapts. No plan change can resolve this.
- **Strategy lead** — whether a `MECHANISM_ONLY` replay result may feed any criterion at all.
  Default taken (no, via `C-VALIDITY`) is conservative and surfaced, not decided.
- **Deferred change with a named owner** — `C-PAIRED` stays `INERT` until
  `current_rung_hold_paper_replay.py` gains `--family-manifest`. Correctly excluded from both plans'
  scope and recorded identically in AUD-09 §12.
- **Operator** — arming, live enablement, the two reserved caps. Named, untouched; no code in this
  item reads, writes or proposes a value for them. No violation found.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
