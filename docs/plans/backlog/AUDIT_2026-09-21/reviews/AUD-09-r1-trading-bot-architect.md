# AUD-09 — Round 1 review (trading-bot-architect, scheduling/pipeline/host-resource lens)

plan id: AUD-09
plan file sha256: b40398080d87f11b32ec7bdd05d4e250758fcef2ef8debef261221bc0cfcdfa6
round: 1
reviewer: trading-bot-architect (independent, adversarial)

## Claims verified

| Ref | Plan claim | Verdict |
|---|---|---|
| No installed timer runs a backtest/replay today | Confirmed: `ls deploy/systemd/*.timer` lists `breezy-exit-window-study`, `family-tally@`, `k1-daily`, `live-tally`, `mb-daily`, `offer-gate-daily`, `position-monitor-report`, `quote-tape-ingest{,-frequent}`, `quote-tape-rotate`, `score-live-trials` — no replay/backtest unit exists. |
| `breezy-exit-window-study.timer` fires at `15:20:00 UTC`, so a new unit at the same slot creates a double-tick | Confirmed: `OnCalendar=*-*-* 15:20:00 UTC` in `deploy/systemd/breezy-exit-window-study.timer`. The plan correctly catches this and defers the 15:20 vs 15:50 choice to the implementer (§6, §12) rather than silently colliding — this is good practice, not a gap. |
| `breezy-studies.slice` carries the shared aggregate ceiling and the host-wide flock pattern the runner is modeled on | Confirmed via the slice file's own header comment (T2/B4/N2 notes), consistent with the plan's `mb-daily-run.sh`-modeled wrapper description. |

I did not re-run the referenced memory-note sufficiency measurement (`quote-tape-is-not-replay-sufficient`, SFO-09-01-only) or the V3 replay envelope (n=1 ≈ 80s/674MB) — both are explicitly flagged UNVERIFIED by the plan itself (§12) and gated behind B2/B5 in the plan's own acceptance criteria, which is the correct posture rather than a defect.

## Answering the specific reviewer challenges

**Is one station-day per run at MemoryMax=4G feasible given recorded replay memory behaviour and the studies-slice flock?** Plausible but not proven inside this plan, and the plan says so itself (§12: "the V3 envelope … is explicitly UNVERIFIED-against-a-fresh-run in its own plan"). The 4G cap is roughly 6x the one measured n=1 sample (~674MB) — reasonable headroom against the single-day driver, and importantly distinct from the *unbounded* multi-day fan-out that produced L-31's incident (memory `replay-driver-memory-grows-unbounded`), because AUD-09b explicitly excludes running `whole_tape_paper_replay.py` on a schedule (§5). The flock (skip-not-kill) correctly prevents concurrency with `k1`/`mb`/`offer-gate`. This is sound design; the residual risk is that the 4G cap could be wrong for a station-day this plan hasn't measured yet (e.g., a day with far more markets/trials than SFO 09-01) — B5's real-run measurement is the intended catch, and OOM-kill is explicitly the "intended, loud outcome" (§6, §9). Acceptable as designed.

**Does the machine-readable result have a schema AUD-10 can consume?** Yes — `replay_results.jsonl`'s field list is fully enumerated (§6) including `schema_version`, and AUD-10b's inputs table (its §6) names this exact file and states it "must refuse an unknown version rather than guess" (§9 here, cross-referenced). The two plans agree on the artefact name and the versioning contract. Genuinely connected, not merely asserted.

**Is `MECHANISM_ONLY` tagging enforced by code or only by convention?** Enforced by code *today*, in the narrow sense that B7's acceptance criterion is "a schema assertion in the runner test" and the runner is specified to always write `validity: "MECHANISM_ONLY"` (§6) — there is no code path that could emit anything else at this point in the dependency chain, so it is not merely aspirational prose. But the plan does **not** specify the flip mechanism: when AUD-11/AUD-12 land, what changes this constant, and what stops a future edit from flipping it without also updating every consumer (AUD-10's `C-VALIDITY`) in lockstep? That is future-plan scope (correctly deferred, per this plan's own dependency table: "AUD-11, AUD-12 flip the validity tag"), so it is not a defect in AUD-09 itself, but it is a gap worth naming explicitly for whichever of AUD-11/AUD-12 lands first, since a hardcoded literal string is exactly the kind of manual step this programme's own lessons (e.g. archive-table train/serve skew) warn drifts silently.

## Defects

**MINOR — validity-flip mechanism not specified even at the "future work" level.** No forward pointer (e.g., "AUD-11/AUD-12 must find and update every writer of `validity=` and every reader of `C-VALIDITY`") is recorded anywhere durable; it lives only in this review's inference from the dependency table. Recommend the plan add one sentence in §12 naming the literal string/constant that must change, so the future implementer has a grep target instead of re-deriving it.

**MINOR — B5's memory/wall-clock thresholds are pinned to a single unverified prior sample.** Author already self-scored this down; I concur it is correctly flagged rather than hidden, so no additional deduction beyond the author's own.

No MATERIAL defect found. The plan's exclusions (no whole-tape scheduling, no PREREG semantics change, no back-fill) are all correctly scoped and cross-checked against the cited files.

## Per-criterion points

| Criterion | Max | Points | Basis |
|---|---|---|---|
| Fidelity to audit gap and completeness | 20 | 17 | Matches author's self-score; SP-4 folded correctly, not duplicated. |
| Technical correctness and evidence grounding | 20 | 18 | Every checkable citation (timers, slice, schedule collision) confirmed exactly; the memory-derived sufficiency claim is honestly gated behind B2 rather than assumed. |
| Implementation specificity and feasibility | 15 | 12 | 15:20 vs 15:50 left to implementer, as author notes — legitimate, bounded ambiguity, not a blocking gap. |
| Acceptance criteria and validation quality | 20 | 16 | B1-B9 measurable; B5 thresholds inherit prior-sample risk as author states. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Queue/lock/OOM/idempotence/empty-queue all handled; the MECHANISM_ONLY-flip gap above is minor and forward-referenced correctly. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Explicit mechanism-vs-edge separation, abandonment criterion, dependency chain to AUD-08/AUD-10 named and artefact-connected. |
| **Total** | **100** | **85** | |

## Required changes to reach 100

1. Add one durable sentence (§12 or a new §14) naming the exact literal/constant AUD-11/AUD-12 must update to flip `validity` away from `MECHANISM_ONLY`, so the dependency isn't only inferable from context.
2. No other change required; B2/B5 already correctly gate the two unverified empirical assumptions.

## Blockers

The two strategy-lead blockers the plan names (R1 trial-id provenance; whether a MECHANISM_ONLY row may ever enter a PREREG v3 context) are real and correctly surfaced as blockers on *statistical use*, not on the build — I concur they do not block AUD-09's own construction and scheduling.
