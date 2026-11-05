# AUD-09 — Review record (Round 1)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: b40398080d87f11b32ec7bdd05d4e250758fcef2ef8debef261221bc0cfcdfa6 (filled by coordinator at save time; plan may have been unchanged since review)
- Round: 1 · Reviewer: code-architect
- Total: 75/100 · Readiness: NOT READY

## Claims verified

| Ref | Plan claim | Result |
|---|---|---|
| §6a "New `src/breezy/analysis/replay_sufficiency.py`" | `src/breezy/analysis/` DOES NOT EXIST (glob returns nothing). `[tool.importlinter]` layers contract (pyproject.toml:71-101) lists app, strategy, runtime, adapters, ingest, persistence\|registry\|normalize, features\|settlement, domain — with `exhaustive = true` (:92). | REFUTED as executable — see N1. |
| §6a reuse of `cli_basis_offer_gate_scan.classify_instance` / `station_days_only_on_corrupt_tape` | CONFIRMED at scripts/analysis/cli_basis_offer_gate_scan.py:391 and :441. Cross-script import is an established repo pattern (`sys.path.insert(0, Path(__file__).resolve().parent)` in 37 scripts including structural_dead_stop.py:48). Feasible **for the script**, not for a `src/` module. |
| §6a "≥30 min afternoon-coverage threshold from structural_dead_stop.py:163-217" | CONFIRMED (`afternoon_coverage_minutes(instants) >= 30.0`, :214). |
| §5 "whole_tape_paper_replay fans over every station-day in one process" | Consistent with the codegraph blast radius (whole_tape_paper_replay.py is a `SUPPORTED_STATIONS` caller); unbounded-memory history taken from L-31/memory, not re-measured. AUTHOR-ASSERTED. |
| §2 "none of the installed timers runs a backtest or replay" | NOT RE-VERIFIED by me (I did not enumerate deploy/systemd/). AUTHOR-ASSERTED. |
| §6b `family_id` read from `deploy/families/<id>.json` | CONFIRMED sound: `load_family_manifest` (persistence/family_manifest.py:211) is the single loader, `family_id` at :339. |

## Defects

**N1 (MATERIAL) — the new package breaks `lint-imports`, which is the plan's own gate.**
§6a creates a new top-level `breezy.analysis` package. The layers contract is `exhaustive = true`
(pyproject.toml:92), so any module directly under the `breezy` container that is not named as a
layer fails the contract. `lint-imports` is step 9 of §7 — the plan fails its own gate on the first
run. Worse, the fix is a real architectural decision the plan does not take: the census core is
specified as reusing `persistence/feather_preflight`, so `analysis` must sit ABOVE `persistence`;
and AUD-10 puts a second module in the same package with different downward dependencies.
REQUIRED: name the `[tool.importlinter]` layers amendment and the exact position in §6, state what
`analysis` may import (and that nothing may import it), and add an acceptance criterion pinning
`lint-imports` green with the package present.

**N2 (MATERIAL) — the append-only contract's dedup key is wrong for the workflow it feeds.**
§6b/§7.5: the runner "skips days already present in `replay_results.jsonl`", keyed
`(station, climate_day)`. The row itself carries `family_id`, `composition_kind`, `strategy`,
`lag_minutes`. So a new family revision — precisely what AUD-10 exists to propose — or a second lag
can never be replayed on an already-consumed station-day, and §9's "QUEUE EMPTY" line will report
the queue as drained while the new family has zero coverage. This silently defeats the
champion-vs-challenger pairing AUD-10's `C-PAIRED` depends on.
REQUIRED: declare the key as `(station, climate_day, family_id, strategy, lag_minutes)` — or state
an explicit re-replay policy — and RED-test it (§7.5 currently tests only the station-day form).

**N3 (MATERIAL) — the crash-safe skip creates a permanent, silent, unattended stall.**
§6b: "crash-safe skip when the output dir already holds `scored_trials_*.parquet`". The completion
marker for the queue is the JSONL row; the skip condition is the parquet. A crash between the two
leaves a day that is still queued (no row) and permanently skipped (parquet present), and the plan
does not say whether the runner then synthesises a row from the existing artefact or exits. Every
subsequent night burns the single daily slot re-selecting the same dead day. §9 enumerates empty
queue, all-insufficient, driver-raise and OOM, but not this.
REQUIRED: make the result row the single completion marker — recover from an existing parquet and
append the row (e.g. `outcome="RECOVERED"`) — or make the skip condition the row, not the parquet.
Add a failure-case bullet in §9 and a RED test.

**N4 (MATERIAL) — a scheduling design decision is delegated to the implementer.**
§6b and §12 leave "reuse the exit-window study's 15:20Z slot by sequencing inside one wrapper, or
move to 15:50Z" open. These are not equivalent: sequencing two 10-24 GB-class studies inside one
wrapper changes the memory envelope, the unit's failure attribution, and what `OnFailure=`/alerting
sees; and AUD-10b §6b then appends a *third* step to the same wrapper. The brief requires
executability without the implementer resolving a material design decision.
REQUIRED: decide it in the plan, with the MemoryHigh/Max and failure-attribution consequence stated.

**n1 (MINOR)** §2's "no installed timer runs a backtest" and §3.3's sufficiency picture are
author-asserted / memory-derived, not re-derived (the plan concedes the latter in §12, with B2 as
the repair). Acceptable, but B2's failure mode should be stated: if B2 disagrees, the queue
estimate and the 30-day abandonment criterion both move.
**n2 (MINOR)** B5's `<2 GB` / `<10 min` derive from an explicitly UNVERIFIED n=1 envelope, so a
legitimate run can fail acceptance without a regression. Give the remedy (record-and-ratchet from
the first real run) rather than only naming the risk.
**n3 (MINOR)** AUD-08 §4/§11 asserts this plan consumes `station_candidates.jsonl`; this plan never
mentions it. State explicitly that AUD-09 does not consume AUD-08.
**n4 (MINOR)** §6a declares a **closed** alphabet containing `VENUE_NEVER_LISTED`, then says the
census "emits `VENUE_NEVER_LISTED_UNCONFIRMED`" — two tokens for one slot in an alphabet whose
closedness is the point. Pick one and list it.

## Strengths (credited)
`replay_results.jsonl` is the best-specified artefact of the three: versioned (`schema_version`),
named writer, named reader (AUD-10), append-only, with an explicit refuse-on-unknown-version rule
(§9). The refusal to fan out multiple days in one process is correctly grounded in the prior
recorded verdict and L-31. Lock/slice/OOM/`Persistent=true` discipline is concrete and modelled on
an existing wrapper. The MECHANISM_ONLY validity tag is a genuine contract, not a caveat in prose.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | Covers "scheduled" and "machine-readable" squarely, folds SP-4 rather than duplicating it, and names the untouched second runner honestly. |
| Technical correctness and evidence grounding | 20 | 14 | Most constraints cited to file/ruling. N1 is a verified technical error against pyproject.toml; two load-bearing premises are author-asserted (n1). |
| Implementation specificity and feasibility | 15 | 10 | Wrapper-level detail is strong; N1 (layer position) and N4 (slot) are unresolved decisions. |
| Acceptance criteria and validation quality | 20 | 14 | B1-B9 mostly objective and B2 is a real falsification test. Nothing covers the dedup key (N2), the crash-recovery path (N3), or lint-imports with the new package; B5 thresholds unverified. |
| Autonomous operation, failure handling, recovery | 15 | 11 | Queue, flock skip-not-kill, OOM cgroup, empty-queue/all-insufficient lines, missed-day self-heal — all good. N3 is a genuine unattended-stall hole; inherits G-14 alerting weakness and says so. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Mechanism-vs-edge separation, explicit abandonment criterion, dependencies by id, PREREG barrier untouched. |
| **Total** | **100** | **75** | |

## Required changes to reach 100
1. Specify the `[tool.importlinter]` layers amendment + `analysis`'s position and allowed imports;
   add a `lint-imports`-green acceptance criterion (N1).
2. Correct the dedup key to include family/strategy/lag, with a RED test (N2).
3. Make the JSONL row the single completion marker and add the crash-recovery failure case (N3).
4. Decide the timer slot and state the memory/failure-attribution consequence (N4).
5. Add the B5 ratchet remedy (n2), the "does not consume AUD-08" statement (n3), and fix the
   duplicated `VENUE_NEVER_LISTED*` token (n4).

## Blockers
- Strategy lead: R1 trial_id provenance and PREREG §9 citability are correctly named as blocking
  any statistical reading, NOT the build. Confirmed as correctly scoped — they do not cap this score.
- No blocker prevents this plan reaching 100; N1-N4 are all author-resolvable.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool (it self-labelled as code-architect)._
