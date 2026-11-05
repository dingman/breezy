# AUD-08 — Review record (Round 1)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: a455939e6807065541690edbf218a145608cb991a8a594f098329b26a75374e9 (filled by coordinator at save time; plan may have been unchanged since review)
- Round: 1 · Reviewer: code-architect (lens: module boundaries, data contracts, idempotency, import layering, portability, YAGNI)
- Total: 67/100 · Readiness: NOT READY

## Claims verified

| Ref | Plan claim | Result |
|---|---|---|
| provider.py:218-224 | unregistered city raises VenuePayloadError with the quoted message | CONFIRMED in substance, line drift: the raise is at provider.py:221-227; `_weather_market_payloads` spans 190-229, not 188-227. Message text quoted verbatim-accurate. |
| provider.py:180-187 | `discovery_candidate_slugs` is the other caller of `_weather_market_payloads` | CONFIRMED (provider.py:181-187). |
| §6 L-1 "InstrumentProvider has no candidate/rejected concept" (author admits the grep was NOT run) | I read `.venv/.../nautilus_trader/common/providers.py` in full (1-393). The class holds only `_instruments`/`_currencies`; API is add/add_bulk/find/get_all/list_all/load*/currency. No rejected, candidate, or unsupported-symbol concept or side-channel. | CONFIRMED — verdict correct, process defect only. |
| §6b "reusing `covered_listed_station_days` (structural_dead_stop.py:163-217)" | Function confirmed at scripts/analysis/structural_dead_stop.py:163-216, ≥30.0 min afternoon rule at :214. | CONFIRMED — but see M4: it lives in `scripts/`, unimportable from `src/breezy/**`. |
| §13 "catalog wrapper pinned to DENSE_STATIONS" | CONFIRMED: `count_covered_listed_station_days_from_catalog(..., cities: Sequence[str] = DENSE_STATIONS)` at structural_dead_stop.py:219-222; `DENSE_STATIONS` defined in cli_basis_setup_win_rate_study.py:126. |
| §4/§11 "AUD-09 consumes 08b's artefact" | REFUTED — see M2. |
| §6 "imports only from parsing/errors — never breezy.runtime" | Consistent with the layers contract (pyproject.toml:71-101), which places `adapters` below `runtime`. No contract violation in the module as placed — but see M1. |

## Defects

**M1 (MATERIAL) — the module placement defeats the plan's only stated value.**
§6 puts `StationCandidate`, `merge_sightings` and `write_station_candidates` in
`src/breezy/adapters/polymarket_us/station_candidates.py`, while §3 and §11 justify 08b almost
entirely as "the portable seam Kalshi needs". A Kalshi adapter can only reuse a
`polymarket_us`-namespaced register by importing a sibling venue adapter (cross-venue adapter
coupling) or by moving/duplicating the module — i.e. the portability benefit is paid for twice.
The dataclasses already carry a `venue` field, which is the tell that the record is venue-neutral.
REQUIRED: put the venue-neutral record + fold + writer in `persistence/` (or a venue-neutral
`domain` module); leave only `UnregisteredCitySighting` *production* in the PM.us provider.

**M2 (MATERIAL) — the consumer named in §4/§11 does not exist.**
§4 states "AUD-09 consumes 08b's artefact" and §11/§4 justify 08b's existence as "AUD-09's input
contract". AUD-09 never reads `station_candidates.jsonl`: its §4 Dependencies list is
{AUD-09a, SP-4 subclass, AUD-11, AUD-12, AUD-10}, its §6a census is built from the tape catalog via
`feather_preflight`/`cli_basis_offer_gate_scan`, and its §6b queue is `(station, climate_day)` over
`SUPPORTED_STATIONS`. 08b's stated raison d'être is unreciprocated.
REQUIRED: either specify in AUD-09 the exact read and the join key, or delete the claim and
re-justify 08b on the Kalshi seam alone (which, with M1 fixed, is defensible).

**M3 (MATERIAL) — an artefact declared to be an inter-stage contract carries no versioned schema.**
`station_candidates.jsonl` (§6b) has no `schema_version`, no named reader, and no
refuse-on-unknown-version rule — while AUD-09's sibling artefact has all three (AUD-09 §6b, §9).
A5 tests byte-idempotence across two runs but never states the record key, so "idempotent" is
untestable as a property rather than as a fixture coincidence.
REQUIRED: add `schema_version`; name the reader and the unknown-version refusal; state
`(venue, city_token)` as the record key and the merge rule (`first_seen_day` never moves,
`last_seen_day` monotone) in the acceptance criteria, not only in prose.

**M4 (MATERIAL) — sufficiency has no specified home; the implementer must take the design decision.**
`sufficiency` is a field on a dataclass in `src/breezy/adapters/...` (§6b), but the only named
computation, `covered_listed_station_days`, is in `scripts/analysis/structural_dead_stop.py:163`
and is not importable from `src/breezy/**` (the repo's cross-script reuse pattern is
`sys.path.insert` from within `scripts/analysis`, used by 37 scripts — a `src/` module cannot use it).
Neither §6 nor §7 says whether `merge_sightings` receives sufficiency as data or computes it.
Compounded by the DENSE_STATIONS pin (confirmed above), which the plan flags in §13 but does not
resolve, leaving A6 not objectively testable for the NYC case.
REQUIRED: state the seam — sufficiency computed in the script and passed into the pure fold as
data — and give the non-dense-city parameterisation in a signature.

**m1 (MINOR)** Line citations drift by ~2-3 lines (see table). Quoted text is accurate.
**m2 (MINOR)** The `unregistered: list[...] | None` **out-parameter** (§6a) is a mutable-argument
anti-pattern against the repo's immutability default. Returning
`tuple[payloads, sightings]` behind a keyword-only `collect_unregistered: bool = False` gives
byte-identical default-path behaviour with the same one-call-site widening (L-12 shape).
**m3 (MINOR)** §6 L-1 grep specified but not run by the author (§13 admits it). I ran the
equivalent read; the verdict holds. Process defect, not a wrong claim.
**m4 (MINOR)** §9's flood cap of "more than 32 new cities in one day" is an uncited magic number.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 13 | Honest about not making stations dynamic; but the delivery chain to AUD-09 is fictional (M2), so 08b's completeness argument does not stand. |
| Technical correctness and evidence grounding | 20 | 15 | Source claims hold; L-1 verdict independently confirmed. Lost on M4 (cited reuse unreachable from the chosen module) and line drift. |
| Implementation specificity and feasibility | 15 | 9 | Specified to dataclass fields and test names, but M1 and M4 are unresolved design decisions. |
| Acceptance criteria and validation quality | 20 | 13 | A1-A4, A7, A8 objective. A5 lacks the key; A6 fixture-only and blocked by the DENSE_STATIONS parameterisation; no criterion covers schema version or reader. |
| Autonomous operation, failure handling, recovery | 15 | 11 | Flood cap, corruption refusal, atomic temp+os.replace, missed-day recovery, independent rollback. Magic 32; no repeated-failure alert beyond unit state. |
| Portfolio objective alignment, scope, dependencies | 10 | 6 | Exemplary ROI honesty and a real abandonment criterion; but the portability justification — its principal value claim — is contradicted by its own module placement (M1). |
| **Total** | **100** | **67** | |

## Required changes to reach 100
1. Move the record/fold/writer out of `adapters/polymarket_us/` to a venue-neutral module (M1).
2. Resolve M2 by either specifying AUD-09's read of the register (file, key, refusal) or dropping the claim.
3. Version the artefact and name writer/reader/key/idempotency rule as acceptance criteria (M3).
4. Specify where sufficiency is computed and the non-dense-city signature (M4).
5. Return the sightings instead of an out-parameter (m2); correct the line citations (m1); run the
   L-1 grep and record it (m3); cite or drop the 32-city cap (m4).

## Blockers
None external. The `registry/sites.toml` re-verification gate is correctly scoped out as a
queued operator/strategy act, not a dependency of this item. Every defect above is
author-resolvable.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool (it self-labelled as code-architect)._
