# AUD-08 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 79ba8151afe24110467b57a941643650f057ad7420d3b43506b20da26a00eaf5 (filled by coordinator at save time)
- Round: 2 · Reviewer: architect (code-architect lens: module boundaries, versioned inter-stage
  contracts, idempotency, import layering, exchange portability, YAGNI)
- Total: 80/100 · Readiness: NOT READY

## Round-1 dispositions verified against the plan body (not §13)

| R1 defect | Claimed | Verified in body? |
|---|---|---|
| M1 — venue-namespaced module defeats portability | ACCEPTED | **FIXED.** §6b places record/fold/writer/reader in `src/breezy/persistence/station_candidates.py`; only sighting *production* stays in the provider. Layer legality re-checked by me against `pyproject.toml:71-101`: `persistence \| registry \| normalize` sits BELOW `adapters`, so provider→persistence is a downward import and legal; the reverse is not. Claim correct. |
| M2 — unreciprocated consumer | ACCEPTED | **FIXED.** H1 (§6b) is a real table (artefact/schema_version/writer/reader/join key/unknown-version refusal/idempotency key) and I diffed it against AUD-09 §6a: same seven rows, same values, same "recorded never queued" behaviour. No drift. |
| M3 — no versioned schema | ACCEPTED | **FIXED.** `STATION_CANDIDATES_SCHEMA_VERSION`, `read_station_candidates`, `UnknownStationCandidateSchemaError` (path + line number + version seen), record key `(venue, city_token)`, merge rule and idempotency key `(venue, city_token, last_seen_day)`, pinned as A6/A7/A8. |
| M4 — sufficiency has no home; DENSE_STATIONS pin | ACCEPTED | **FIXED for the seam.** The fold signature is given, sufficiency is passed in as data, and the non-dense parameterisation is the explicit `cities=(city,)` argument to `count_covered_listed_station_days_from_catalog` (`structural_dead_stop.py:219-222`). See A8-2 for what the seam still cannot produce. |
| m1 line drift | ACCEPTED | **FIXED and re-verified by me:** `discovery_candidate_slugs` at `provider.py:181-187`; `_weather_market_payloads` spans `:190-229`; the unregistered-city raise is at `:221-227` with the quoted message verbatim-accurate; `data.py:1253-1267` is the blanket `except Exception` + RED log + fall-through. The blast-radius/livelock reading in §3 is correct: the raise precedes `accepted.append`, so the whole pass is refused. |
| m2 out-parameter · m3 L-1 grep · m4 magic 32 | ACCEPTED | **FIXED.** Keyword-only flag returning `(payloads, sightings)`; L-1 grep output recorded (I independently confirmed `InstrumentProvider` holds only `_instruments`/`_currencies` in round 1 — verdict unchanged); flood cap now registry-derived. |

Priority re-cut to P1 with a stated urgency counter-argument: accepted, the argument is evidenced
and the blast radius is conceded rather than argued away.

## Defects found in revision 2

**A8-1 (MATERIAL) — the register's own input artefact does not exist in the plan, and its
existence contradicts §1.**
§6b's emitter "reads the recorder's sighting sidecar (**written by 08a**, one JSONL line per cycle,
bounded by `city_codes` cardinality)". But §6a — the complete 08a change list — writes no file: it
adds `collect_unregistered`, exposes `self._unregistered_city_sightings`, and logs one WARN. And §1
states 08a is "Adapter-side, **no new artefact, no new file format**". Both cannot be true. The
sidecar is a fourth inter-stage artefact (live node/recorder process → nightly script) and it is the
ONLY one of the four that carries none of the standard this revision just established for the
others: no path, no `schema_version`, no writer function, no reader, no unknown-version refusal, no
record key, no rotation/compaction, and no statement of who may write it. Two processes run
`PolymarketUSInstrumentProvider` (the recorder, §12, and the trade node), so concurrent appenders are
the default case and no ordering/locking rule is given. No acceptance criterion (A1–A11) mentions it;
§9's corruption bullet covers the *register*, not the sidecar.
REQUIRED: either (a) specify the sidecar as a first-class artefact under the same standard as
`station_candidates.jsonl` — module, path, `schema_version`, writer/reader, append-vs-rotate, the
single sanctioned writer, concurrent-writer rule — move it into the 08a change list, correct §1, and
add an acceptance criterion; or (b) delete it and have the emitter obtain sightings another way
(e.g. 08a writes nothing and the emitter re-parses the last recorded discovery payload), stating that
mechanism explicitly.

**A8-2 (MATERIAL) — the NYC record, and therefore A9, has no producer in the specified data flow.**
§6b claims "**NYC** … the register records it with its real capture-derived sufficiency, which makes
the exclusion legible outside a docstring for the first time", and **A9** tests register sufficiency
"for a registered-but-uncaptured city" against `count_covered_listed_station_days_from_catalog`. But
the register's sole input is `merge_sightings(existing, sightings, …)`, and a sighting exists only
when `parsed.city not in city_set` (`provider.py:221`). NYC IS in `city_codes` — it is one of the
five `(polymarket_us, city)` registry pairs the plan itself enumerates (`sites.toml:117,…`) — so NYC
can never produce a sighting and can never enter the fold. The fold is also explicitly forbidden from
computing sufficiency, so it cannot synthesise the row either. A9 is therefore not reachable from the
specified design, and the three "richer" statuses (`REGISTRY_ONLY_NO_CAPTURE`,
`CAPTURED_INSUFFICIENT`, `CAPTURE_SUFFICIENT`) have no producer at all — only
`NO_SETTLEMENT_TRUTH` does, which §6b concedes is "true of every sighting by construction today".
That makes three quarters of the `Sufficiency` alphabet dead on arrival (a YAGNI failure as well as a
testability one).
REQUIRED: give the fold an explicit registry-derived **seed set** (the venue's registered-but-
unsupported cities) as a second named input with its own key rule, so NYC's row has a producer and
the richer statuses are reachable — or delete the NYC claim, delete the unreachable statuses, and
restate A9 against a case the design can actually produce.

**a1 (MINOR) — the `collect_unregistered` signature is not expressible under `mypy --strict`.**
§6a gives one function whose return type depends on a bool argument
(`tuple[...]` vs `tuple[tuple[...], tuple[...]]`). `[tool.mypy] strict = true` covers
`src/breezy/adapters` (pyproject.toml:159-168) with no waiver for this module, so the declared return
must be a union and `discovery_candidate_slugs` (`provider.py:187`) would fail to iterate it without
narrowing. REQUIRED: specify `@overload` on the literal bool, or two functions (a shared inner + two
thin wrappers). Cheap, but it is the kind of thing that turns a "GREEN" step into a redesign.

**a2 (MINOR) — H2 is described as fully declined here, but AUD-10 still reads this artefact.**
§6b: "AUD-10b consequently does **not** read this artefact, **and** … with the register's candidate
count recorded in `criteria.json`". Recording the register's candidate count requires reading the
register. The decline is therefore partial and the partial read has no contract (no reader, no
unknown-version behaviour, no missing-file behaviour) — the exact hole M3 closed for H1. REQUIRED:
pick one — drop the count from `C-STATIONS` (leaving a pure subset predicate), or specify the read as
a bounded hand-off in all three files and stop calling H2 "declined". Scored against AUD-10, where
the criterion lives; noted here for consistency.

**a3 (MINOR)** §6b's register path and the A7 idempotency key are stated, but no compaction/retention
rule exists for a venue that churns city tokens (the author concedes this in §13). Unbounded, but
bounded in practice by the flood cap; genuinely minor.

## Strengths (credited)

The 08a/08b re-split is the right decomposition: the livelock fix carries no artefact, no format and
no schedule, and is independently revertible. The module move to `persistence/` is correct and its
layer argument is verifiable, not asserted. The venue-neutral record + pure fold + I/O-at-the-edges
shape (sufficiency in, no I/O in the fold) is exactly the seam a second venue needs. The refusal to
auto-promote a candidate to a capture subscription, grounded in the shared WS subscription cap, is
disciplined YAGNI. The ROI section is unusually honest and the abandonment criterion is correctly
scoped to 08b only.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 08a closes the real load-bearing finding and is complete. 08b's claim to make the NYC exclusion legible is not deliverable by its own data flow (A8-2). |
| Technical correctness and evidence grounding | 20 | 16 | Every external citation I re-opened is exact (provider.py:181-187/190-229/221-227, data.py:1253-1267, pyproject layer order, structural_dead_stop cities=). Lost on internal inconsistency: §1 vs §6b on whether 08a writes an artefact (A8-1). |
| Implementation specificity and feasibility | 15 | 10 | Module, fold signature, sufficiency seam, record key all decided. A whole artefact (the sidecar) is unspecified, and the one function signature given is not strict-typable (a1). |
| Acceptance criteria and validation quality | 20 | 16 | A1–A8, A10, A11 objective and property-shaped. Nothing covers the sidecar; A9 is not reachable from the design. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Livelock closed with a two-cycle test, registry-derived flood cap, corruption refusal, three-failure alert escalation, independent rollback. The unspecified sidecar has no concurrency, rotation or corruption story, and it is written from a live process. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Zero-ROI honesty, real abandonment criterion correctly scoped, exclusions each reasoned, no operator-cap or enablement contact. |
| **Total** | **100** | **80** | |

## Required changes to reach 100
1. Specify or eliminate the 08a sighting sidecar under the same artefact standard as the register, and
   remove the §1 "no new artefact" contradiction; add an acceptance criterion for it (A8-1).
2. Give NYC / the registered-but-unsupported cities an explicit seed input to the fold, or delete the
   NYC claim and the unreachable `Sufficiency` statuses and restate A9 (A8-2).
3. Give `_weather_market_payloads` an `@overload`-based (or two-function) signature that is valid
   under `mypy --strict` (a1).
4. Make the H2 decline consistent with `C-STATIONS` across all three files (a2).

## Blockers
None external. The `registry/sites.toml` re-verification gate remains correctly scoped as a queued
operator/strategy act, not a dependency. Both material defects are author-resolvable.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
