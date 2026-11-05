# AUD-08 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 79ba8151afe24110467b57a941643650f057ad7420d3b43506b20da26a00eaf5
- Round: 2 · Reviewer: trading-bot-architect (autonomous-loop/pipeline lens)
- Total: 78/100 · Readiness: NOT READY

## Round-1 defect verification (both round-1 reviewers' records read)

| Defect | Verified fixed in body? |
|---|---|
| P/blast-radius mismatch (P2→P1, livelock split into 08a) | YES — §1/§4/§7 step 3/A2 all present and match the source (`data.py:1253-1267` blanket except confirmed at that span; `provider.py:221-227` raise confirmed). |
| M1 venue-namespaced module | YES — `src/breezy/persistence/station_candidates.py`; layer legality argument checked against `pyproject.toml:71-101` and holds (`persistence` is a real existing layer below `adapters`). |
| M2 unreciprocated hand-off | YES — H1 table identical in AUD-08 §6b and AUD-09 §6a (byte-compared); H2 declined identically in AUD-08/09/10. |
| M3 unversioned artefact | YES — `STATION_CANDIDATES_SCHEMA_VERSION`, `UnknownStationCandidateSchemaError`, A8. |
| M4 sufficiency seam | YES — pure-fold signature given; `count_covered_listed_station_days_from_catalog(catalog_root, cities=(city,))` and the `>=30.0` rule verified at `scripts/analysis/structural_dead_stop.py:214,219-222` exactly as cited. |
| m2 mutable out-param | YES — `collect_unregistered: bool = False` return-tuple form, verified against current `provider.py:190-229`. |
| m4 magic `32` | YES — replaced with a registry-derived cap; `src/breezy/registry/sites.toml` confirmed to hold exactly 5 `polymarket_us` cities (NYC/SFO/MIA/MDW/LAX). |

No round-1 acceptance was falsely claimed. Verdict on the rejected-option question (out of scope for
AUD-08 itself — see the AUD-10 record) does not touch this plan directly.

## Claims verified (this round, fresh read)

| Ref | Claim | Result |
|---|---|---|
| §3.2 `VenuePayloadError` raised at `provider.py:221-227` on an unregistered city | CONFIRMED verbatim, including the exact refusal text. |
| §3.4 blanket `except Exception` at `data.py:1253-1267`, cycle failure is non-fatal but permanent | CONFIRMED — the loop logs RED and re-sleeps; nothing clears the registry gap without a human edit. |
| §4 P1-not-P0: registry covers all 5 cities the venue has ever listed | CONFIRMED — `sites.toml` has exactly NYC/SFO/MIA/MDW/LAX under `polymarket_us`; PROGRESS.md:31 "5 cities" matches. |
| §6b sufficiency computation cites `structural_dead_stop.py:219-222`/`:214` | CONFIRMED exactly (function signature, `cities=` param, `>=30.0` afternoon-coverage rule). |
| §6b "It reads the recorder's sighting sidecar (written by 08a...)" | **REFUTED as a completed design** — see MATERIAL M5 below. §6a never specifies any such writer. |

## Defects

**MATERIAL M5 (new this round) — 08b's emitter presupposes an artefact 08a never commits to
writing; the internal 08a→08b hand-off is undefined.** §6b's Emitter bullet states the script
"reads the recorder's sighting sidecar (written by 08a, one JSONL line per cycle...)". §6a's own
bullets, §7's RED-test list (steps 1-6), and the acceptance table (A1-A11) describe only an
**in-process** artefact: `self._unregistered_city_sightings` held on the live
`PolymarketUSInstrumentProvider` inside the long-running `breezy-quote-tape.service` process, plus
one WARN log line per cycle. `scripts/analysis/station_candidate_register.py` (08b) is a **separate
process**, invoked later by the rotate wrapper — it cannot read another process's Python attribute.
Nothing in the plan assigns responsibility for turning the recorder's in-memory sightings into the
durable sidecar the emitter is stated to consume: no writer, no path, no schema, no atomicity
guarantee, no crash-recovery statement (recorder restarts and loses `_unregistered_city_sightings`
today — that data is never durable), and no RED test or acceptance criterion covers it. This is a
material, unresolved design decision the plan leaves to the implementer, exactly the class of gap
the rubric asks to be checked ("executable without resolving a material design decision" — it is
not). The author's own §13 self-score buries this as a minor residual ("the recorder sidecar's exact
path/format is described but not given as a schema") — it understates the gap: the artefact is not
merely under-specified, its writer does not exist in the plan at all.
REQUIRED CHANGE: in §6a, name the sidecar's writer (either the live recorder appends one durable
JSONL line per reload cycle with an atomic write, or the register script itself makes the discovery
call redundant by reading `_resolved_market_reasons`-adjacent state some other already-durable
recorder artefact) — give path, schema, one-line-per-cycle framing, atomicity, and a RED test +
acceptance criterion (an A12) exercising a recorder-crash-mid-write case. Until this exists, 08b is
not buildable as specified.

**MINOR — H2's "next step to eligibility" has no active trigger or named owner-of-record.** §12's
BLOCKER states `sites.toml` re-verification is required to widen the allow-list, and a candidate
record "queues it," but nothing surfaces a non-empty register to a human: no alert on the register
transitioning from empty, no PROGRESS.md line, only the passive 60-day abandonment review in §11.
This is honest disclosure (the plan states the open question rather than hiding it) and the wider
"whether to expand" decision is correctly left to a ruling — but the mechanism by which anyone would
*notice* a candidate and open that ruling is unspecified beyond a periodic manual review.
REQUIRED CHANGE (minor, not score-capping at MATERIAL level given the honest disclosure): add one
line to §9 or §10 naming the trigger — e.g., a WARN/alert (reusing the shipped alert sink) the first
time `distinct_climate_days` for any candidate crosses a small threshold (e.g. 1), naming who is
expected to act on it (strategy lead, via a ruling artefact).

## Strengths (credited)
The livelock fix (08a) is well-specified, RED-tested at the exact failure shape (§7 steps 1-3, A1-A3),
and the blast-radius argument is verified against source rather than asserted. The Nautilus null
hypothesis grep is actually run with recorded output. The flood cap and idempotency key are properly
derived from real repo properties rather than invented. Scope exclusions (no `sites.toml` edit, no
widening `SUPPORTED_STATIONS`, no subscription) are all correctly held.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | Livelock and register both addressed; H2's declared limit is honest. Minor point lost on the missing eligibility trigger. |
| Technical correctness and evidence grounding | 20 | 18 | Every re-checked citation (raise site, blanket except, registry city count, sufficiency function) confirmed exactly. |
| Implementation specificity and feasibility | 15 | 9 | MATERIAL M5: the 08a→08b hand-off artefact is undefined; the plan is not executable as written without the implementer inventing a schema and writer. |
| Acceptance criteria and validation quality | 20 | 14 | A1-A11 are objective for what they cover, but nothing tests the sidecar write/read path, which is the actual inter-process bridge 08b depends on. |
| Autonomous operation, failure handling, recovery | 15 | 11 | Livelock recovery and flood/corruption handling are solid; the sidecar's own crash/atomicity behavior is entirely unaddressed because the artefact doesn't have a spec. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Honest zero-ROI statement for PM.us, hand-offs named, abandonment criterion correctly scoped to 08b only. |
| **Total** | **100** | **78** | |

## Required changes to reach 100
1. Specify the 08a→08b sidecar: writer, path, schema, atomicity, crash behavior, RED test, acceptance criterion (M5).
2. Name an active trigger (alert or PROGRESS line) for a non-empty candidate register, and its owner (minor).

## Blockers
- **BLOCKER (operator/strategy-lead, correctly named, not decided here):** widening `registry/sites.toml`
  requires that file's own pre-production re-verification gate. Not a defect in this plan; correctly
  deferred.
- **BLOCKER (unresolved by this review, testable):** whether the venue would ever actually list a 6th
  city is unobserved; §12 states this honestly.
