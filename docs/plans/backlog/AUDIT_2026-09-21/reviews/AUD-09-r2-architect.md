# AUD-09 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 03295e8e29f2131d2fc6b083db42040f95c965ed24d6987f2084e62967fafdb5 (filled by coordinator at save time)
- Round: 2 · Reviewer: architect (code-architect lens)
- Total: 81/100 · Readiness: NOT READY

## Round-1 dispositions verified against the plan body

| R1 defect | Claimed | Verified in body? |
|---|---|---|
| N1 — `breezy.analysis` breaks `exhaustive = true` | ACCEPTED | **PARTIALLY FIXED.** The layer position IS decided, the literal `layers` list and two contracts are quoted, the allowed-import set is enumerated, and B10 exists. But the literal config as written does not pass `lint-imports` — see 09-1. The position itself (below `app`, above `strategy`) is sound and I confirm it grants the downward reach the census needs: `persistence \| registry \| normalize`, `features \| settlement` and `strategy` are all below it in `pyproject.toml:75-91`, and `app` is the only package above it, closed by the first forbidden contract. Identical text in AUD-10 §6 — I diffed both blocks: layers list, both contracts, and the allowed-import sentence are character-equivalent. |
| N2 — dedup key too narrow | ACCEPTED | **FIXED as text, but the new dimension has no producer — see 09-2.** Key is now `(station, climate_day, family_id, strategy, lag_minutes)` with a re-replay policy, a RED test and B11. |
| N3 — parquet-keyed skip creates a permanent stall | ACCEPTED | **GENUINELY FIXED.** The JSONL row is the single completion marker; `RECOVERED` / `FAILED` paths, the §9 failure-case bullet, the §7.5 test and B12 are all present and mutually consistent. This is the strongest repair in the revision. |
| N4 — timer slot undecided | ACCEPTED | **FIXED and independently verified by me.** `grep OnCalendar= deploy/systemd/` returns exactly 01:35, 02:05, 09:00, 13:30, 14:15, 14:30, 15:00, 15:20, 17:20, `00,06,12,18:15` and `*:0/15` — the plan's list is complete and correct, and 15:50 is free (and not on the `*:0/15` stepper). 15:50 + `TimeoutStartSec=1800` also lands before the 16:35Z protected window. The memory / failure-attribution / lock-contention consequences are all stated, including the accepted cost. |
| n1–n4 minors | ACCEPTED | All present: B2's two-direction failure mode (§9), B5 record-and-ratchet (§7.11), H1 made real rather than disclaimed, single `VENUE_NEVER_LISTED_UNCONFIRMED` token with `CANDIDATE_UNSUPPORTED_STATION` added, `REPLAY_VALIDITY` single definition site pinned by B7's grep. |

## Defects found in revision 2

**09-1 (MATERIAL, NEW — introduced by the N1 fix, identical in AUD-10) — the second forbidden
contract cannot pass, so B10/C10 are unattainable as written.**
`import-linter`'s `ForbiddenContract.allow_indirect_imports` is `fields.BooleanField(required=False,
default=False)` (`.venv/lib/python3.13/site-packages/importlinter/contracts/forbidden.py:72`), and at
`:131-143` a false value takes the `graph.find_shortest_chains(...)` branch — i.e. **indirect chains
are violations unless the flag is explicitly set true**. The repo already knows this: the `.com`
adapter contract sets `allow_indirect_imports = true` with a comment saying so
(`pyproject.toml:116-121`), and the archive contract sets it `false` deliberately. The plan's second
contract omits the flag entirely, while §6 simultaneously states `analysis` **may import**
`strategy`, `runtime`, `adapters`, `ingest`. Every one of those reaches Nautilus: I confirmed
`breezy.strategy.current_rung_hold.config` imports `nautilus_trader.model.identifiers` and
`nautilus_trader.trading.config.StrategyConfig` at `config.py:59-60` — and `SUPPORTED_STATIONS`, the
very symbol §6 cites as the reason `analysis` sits above `strategy`, lives in that module
(`config.py:76`). With `nautilus_trader` rooted in the graph (`root_packages`, `:68`), the chain
`breezy.analysis.replay_sufficiency → breezy.strategy…config → nautilus_trader` is found and the
contract breaks on the first run. The enumerated allow-set and the contract are mutually inconsistent
as stated.
REQUIRED: add `allow_indirect_imports = true` to the "offline analysis layer never imports Nautilus"
contract with the same rationale the `.com` contract carries (the property wanted is *no direct
adoption*), **or** re-source `SUPPORTED_STATIONS` from a Nautilus-free module. Make the identical
change in AUD-10 §6 and say so, since B10 and C10 are declared to be the same criterion.

**09-2 (MATERIAL) — `family_id` is in the queue key and on every row, but nothing can vary it, and
the driver is not parameterised by the family the row names.**
§6b's step-3 command invokes `scripts/analysis/current_rung_hold_paper_replay.py` with
`--strategy/--station/--climate-day/--tape-instance-id/--lag-minutes/catalogs/--output-dir`. I read
that script's parser (`:1076-1113`): there is **no** `--family`, no manifest path, and no fee-
coefficient argument. So (i) the replayed strategy is built from config defaults — including
`required_fee_coefficient = Decimal("0.06")` (`config.py:226`), which the live family's registered
theta no longer equals (memory `venue-fee-theta-drift-2026-09-17`) — while the row is stamped with a
`family_id` read from a manifest that the engine never saw. That is precisely the "statistic attached
to the wrong family" class AUD-10 §11 cites as this repo's most expensive recurring error, and the
train/serve-skew shape of memory `archive-table-train-serve-skew`. (ii) §6b says `family_id` is read
from "`deploy/families/<id>.json`" without ever binding `<id>` — an unresolved design decision left to
the implementer, which the brief forbids. (iii) Because the runner can only ever name one family, the
five-tuple key degenerates to `(station, climate_day)` in practice, and B11's regression test
("a day replayed under family A **is** selected for family B") can only be satisfied by a synthetic
fixture, never by the deployed runner — so N2's fix is textual, not operative, and AUD-10's
`C-PAIRED` still has no producer of challenger rows.
REQUIRED: decide and state the family dimension end to end — which manifests the runner enumerates
(armed only? a declared challenger list under `deploy/families/`?), and how the family's parameters
actually reach the engine (a `--family-manifest` flag on the driver threading
`required_fee_coefficient`, which is a runner-item change and must be added to §5's in-scope list
since §5 currently excludes driver changes). If the answer is "armed family only", then say so, drop
`family_id` from the *queue* key, keep it as provenance, and record explicitly that AUD-10's
`C-PAIRED` is unsatisfiable until a challenger-replay path exists.

**09-3 (MATERIAL) — `replay_sufficiency.jsonl` is an inter-stage artefact that does not meet the
standard this revision imposes on the other two.**
It is written by the census (AUD-09a) and read by the runner (AUD-09b) across a process boundary and
across a merge boundary (§7 lands them in separate steps). It carries a `schema_version` field on
`ReplaySufficiency` and nothing else: no named writer, no named reader, no
`UnknownReplaySufficiencySchemaError`/refuse-on-unknown-version rule, no declared record key, no
hand-off table — while `station_candidates.jsonl` (H1) and `replay_results.jsonl` (H3) each carry all
seven rows. A stale file from a previous schema is silently consumed by the runner's target selection,
which is the exact failure H1/H3 refuse. B3 tests byte-idempotence, not version discipline.
REQUIRED: give it the same seven-row treatment — module (`src/breezy/analysis/replay_sufficiency.py`),
`REPLAY_SUFFICIENCY_SCHEMA_VERSION`, `write_/read_replay_sufficiency`, refuse-on-unknown-version,
record key `(station, climate_day)`, rewrite-atomically semantics — and add an acceptance criterion.

**b1 (MINOR) — the §6b command omits a required driver argument.** `--asos-cache-csv` is
`required=True` (`current_rung_hold_paper_replay.py:1082`) and does not appear in the plan's command
block, which otherwise enumerates its flags. As written the invocation exits on argparse.

**b2 (MINOR)** `classify_station_day`'s span input type is prose, not a signature (author concedes in
§13). Minor, but it is the seam between the reused script-side scanners and the pure core.

## Strengths (credited)

N3's repair is exemplary: the completion marker is a single artefact, both crash branches are
enumerated, and the "day never permanently queued-and-skipped" property has its own criterion. The
timer decision is made with its consequences priced (memory envelope, failure attribution, the
accepted skip-on-contention cost) rather than deferred. The L-1 verdict is grounded in a prior
recorded Breezy verdict plus L-31 rather than re-derived. The MECHANISM_ONLY tag is a real contract
with a single definition site and a grep criterion over it. H1's "recorded, never queued" limit is the
honest version of the G-05→G-06 connection and is stated identically in AUD-08.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | "Scheduled" and "machine-readable" are both squarely covered; SP-4 folded not duplicated. The family dimension the promotion loop needs is named but not delivered (09-2). |
| Technical correctness and evidence grounding | 20 | 15 | Timer ticks, layer order and the absent package re-verified and correct. Lost on 09-1 (a verified error against import-linter's own default) and on the `family_id`/driver-parameterisation mismatch verified against the driver's parser. |
| Implementation specificity and feasibility | 15 | 11 | Wrapper, unit, memory caps, selection rule and recovery all concrete. `<id>` is unbound, the command omits a required flag, and the quoted contract does not run. |
| Acceptance criteria and validation quality | 20 | 16 | B1–B9, B12, B13 objective; B2 a real falsification test. B10 unattainable as written; B11 can only pass synthetically; nothing covers the census artefact's version discipline. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Crash recovery, duplicate-key hard error, skip-not-kill, OOM cgroup, empty-queue and all-insufficient lines, honest G-14 inheritance. Deducted for the unversioned census hand-off (09-3). |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Mechanism-vs-edge separation held, abandonment criterion with a stated adjustment, dependencies by id, PREREG barrier and permit path untouched. |
| **Total** | **100** | **81** | |

## Required changes to reach 100
1. Fix the Nautilus forbidden contract (`allow_indirect_imports = true`, or a Nautilus-free source for
   `SUPPORTED_STATIONS`) — identically in AUD-10 (09-1).
2. Decide the family dimension end to end: which manifests are enumerated, how the family's parameters
   reach the engine, and — if only the armed family is replayable — say so and record `C-PAIRED` as
   unsatisfiable until a challenger path exists (09-2).
3. Bring `replay_sufficiency.jsonl` up to the H1/H3 artefact standard and add a criterion (09-3).
4. Add `--asos-cache-csv` to the command block (b1); give `classify_station_day` a signature (b2).

## Blockers
- Strategy lead: R1 `trial_id` provenance and PREREG §9 citability remain correctly scoped as blocking
  a statistical reading, not the build. They do not cap this score.
- No external blocker prevents 100; 09-1 to 09-3 are all author-resolvable.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
