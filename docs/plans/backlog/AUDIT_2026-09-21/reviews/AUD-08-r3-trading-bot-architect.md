# AUD-08 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 5b2b5569831a48a76bfb7599a1d2aa477ef1c9d777d431ac3db51ab9f9604fad
- Round: 3 · Reviewer: trading-bot-architect (autonomous-loop/pipeline lens)
- Total: 100/100 · Readiness: READY

## Round-2 defect verification (both round-2 reviewers' records read, against the plan BODY not §13)

| Defect | Verified fixed in body? |
|---|---|
| MATERIAL M5/A8-1 — 08a→08b sighting sidecar had no writer, path, schema, concurrency or crash rule, and contradicted §1's "no new artefact" | YES. §6b.1 is a full artefact table: module `src/breezy/persistence/station_candidates.py`, path `sightings/sightings-<UTC day>.jsonl`, `SIGHTING_SCHEMA_VERSION`, `append_sighting`/`read_sightings`, `UnknownSightingSchemaError`, trailing-partial-line-vs-non-final-line crash rule, 35-day pruning. §1 now states the sidecar lives in 08b, not 08a, resolving the contradiction rather than re-wording it. Single-writer enforced by construction: `sighting_sink: SightingSink \| None = None` on `PolymarketUSInstrumentProvider`, injected at `factories.py:517`. **I independently re-read `factories.py:514-594` this round**: `_shared_polymarket_us_instrument_provider` (`:516-537`) has exactly one call site in this file, `PolymarketUSLiveDataClientFactory.create` (`:553-594`), which receives a `PolymarketUSDataClientConfig` that already discriminates recorder-vs-trade-node behaviour today (`:619-622`'s comment: "The recorder's knob... the trade node's config leaves it False"). This confirms the injection point the plan names is real and singular, not invented — the same config object that already distinguishes the two processes is available at the exact call site where `sighting_sink` would be threaded. `AlertSink`'s cited shape (`health.py:385-394`, one-method Protocol `emit(self, payload: AlertPayload) -> None`) is exact, confirming "mirroring `runtime/health.py:385 AlertSink`" is not a loose analogy. |
| MATERIAL A8-2 — NYC could never produce a sighting; A9 unreachable | YES. `seed_cities` second input to `merge_sightings` (§6b.3), computed in the script from `default_registry().pairs()` minus `SUPPORTED_STATIONS`; `Origin = Literal["SIGHTING","REGISTRY_SEED"]`; every `Sufficiency` value now has a producer. |
| MINOR a1 — signature not `mypy --strict`-expressible | YES. Two `@overload` on `Literal[True]`/`Literal[False]`, A13. |
| MINOR a3 — no retention rule | YES. §6b.2: no expiry, flood-cap-bounded growth, 180-day compaction (not deletion), A15. |
| MINOR (tba) — no trigger from a non-empty register to a human | YES, and taken further. §6b.4's one-shot `BREEZY_STATION_CANDIDATE_NEW` alert, keyed on `first_seen_day == today` (durable, not `AlertState`, which is correctly identified as in-memory/per-process per its own docstring), A16. §6c's eight-step eligibility table names an owner per step. |

No round-2 acceptance is falsely claimed in §13; every disposition I re-checked against the body matches.

## Claims verified this round (fresh read against current source)

| Ref | Claim | Result |
|---|---|---|
| §6a `_weather_market_payloads` raise at `provider.py:221-227`, unconditional, precedes `accepted.append` at `:228` | CONFIRMED verbatim against current `provider.py:190-229`. |
| §6b.1 `factories.py:517 _shared_polymarket_us_instrument_provider`, single call site at `:589-594` | CONFIRMED — re-read the full function and its only caller in this file. |
| §6b.1 `AlertSink` mirrored shape | CONFIRMED exact at `health.py:385-394`. |
| §9 alert degrades to `LoggingAlertSink` when unconfigured, contained by `emit_alert` | Consistent with the AlertSink/AlertPayload shapes read; not independently re-derived this round beyond the Protocol check, no contradiction found. |

## Defects

None found. Both round-2 MATERIAL defects are genuinely closed — not re-worded — and independently re-verified against source this round, including the one specific thing the coordinator asked me to check (the `sighting_sink` injection seam and the trade-node-cannot-become-a-second-writer property): the seam exists at exactly the cited line, has exactly one call site, and that call site already carries the discriminator (`config.subscribe_trades`-shaped) needed to decide which process gets the file-backed sink. A14's RED test (trade-node composition passes `sighting_sink=None`) is therefore testable against a real, singular injection point, not a hypothetical one.

## Strengths (credited)

The 08a/08b split remains the correct decomposition. The sidecar is now genuinely a first-class artefact carrying the same seven-row discipline as the register (schema version, writer, reader, unknown-version refusal, crash behaviour split into the two real cases). The eligibility-sequence table (§6c), identical across AUD-08/09/10, is an unusually honest piece of engineering communication: it states exactly which two of eight steps this item owns and refuses to let a candidate record be mistaken for progress toward trading. The new-candidate alert closes the "detector without delivery is not a control" gap named in this repo's own memory.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 08a closes the livelock; 08b delivers the register, the sidecar, and the notification; §6c honestly states the eight-step path and that this item owns exactly two of its steps — that is completeness about G-05/G-07, not an overclaim of closure. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I re-opened (raise site, blanket except, `factories.py:517`, `AlertSink`) is exact. No internal contradiction remains between §1 and §6b. |
| Implementation specificity and feasibility | 15 | 15 | Sidecar, sink injection point (now independently confirmed singular and real), overload signature, seed input, retention, and alert dedupe are all decided to the level an implementer can build from without inventing a design. |
| Acceptance criteria and validation quality | 20 | 20 | A1–A16 are objective; A9 has a real producer; A12/A14/A16 cover the artefact, writer uniqueness, and the notification with RED tests named. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Livelock closed with a two-cycle test; two distinct sidecar crash cases (trailing partial vs. non-final malformed) handled correctly; flood cap; repeated-failure alert escalation; a candidate now pushes rather than waits to be found. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Zero-ROI honesty preserved; H1 real, H2 declined without residue; abandonment criterion scoped correctly; every out-of-scope step named with an owner. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers

- **BLOCKER (operator/strategy-lead, correctly named, does not cap this plan's score):** widening `registry/sites.toml` requires that file's own pre-production re-verification gate; a candidate record queues and announces it but does not authorise it.
- **BLOCKER (strategy lead, OUTSIDE this backlog, correctly named):** a fifth station has no measured archive table; extending the frozen corpus is a separate, larger item.
- **Unresolved but testable, not a blocker:** whether the venue would ever list a 6th city is unobserved; §12 states this honestly and it is the reason 08a is P1 rather than P0.
