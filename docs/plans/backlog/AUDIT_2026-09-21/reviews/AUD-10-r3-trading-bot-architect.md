# AUD-10 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 18a2e1fab679c80a996e078a777380707f0c0b84f8bc3cae01a09057f29aad6d
- Round: 3 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 100/100 · Readiness: READY

## Round-2 defect verification (both round-2 reviewers' records read, against the plan BODY not §13)

| Defect | Verified fixed in body? |
|---|---|
| MATERIAL 10-1 (= AUD-09 09-1) — forbidden contract cannot pass without `allow_indirect_imports = true` | YES. §6 quotes the contract with the flag and the `.com`-contract-precedent rationale, identical to AUD-09 §6. Re-derived independently against `importlinter/contracts/forbidden.py:72,131-143` this round — the underlying hazard is real and the fix genuinely neutralises it. |
| MATERIAL 10-2 (= AUD-08 a2) — H2 called "declined" while `C-STATIONS` recorded a register candidate count, which requires a read with no reader/version/missing-file contract, and would make a missing register refuse a proposal | YES. §6b.2's H2 is now declined **without residue**: the count clause is deleted; `C-STATIONS` (§6b.3) is a pure subset predicate over the proposal's own draft manifest, reading no other artefact. The visibility the count was reaching for is delivered by AUD-08b's alert instead (verified identical language in AUD-08 §6c and AUD-09 §6a). |
| MATERIAL 10-3 — no input artefact bound per predicate, `C-PAIRED` had no producer | YES. §6b.3's table names an input artefact and an absent-input behaviour for every predicate. `C-PAIRED` is declared `INERT` (never `false`) with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, a named blocking change (the `--family-manifest` flag on the driver, mirrored in AUD-09 §12), and C14 (a run with an `INERT` predicate can never emit `PROPOSAL`). I independently re-verified the underlying fact this round: `current_rung_hold_paper_replay.py:932-934` builds `CurrentRungHoldConfig` with `required_fee_coefficient` defaulting to `Decimal("0.06")` (`config.py:226`) against the armed manifest's `"0.0695"` (`deploy/families/pm_us_crh_v4.json`, grepped directly) — so `C-VALIDITY`'s new `params_match` clause (C16) is grounded in a real, measured divergence, not an assumed one. |
| MINOR c1 — non-`app` callers of the narrowed functions unstated | YES. §6 enumerates `app/trade.py:48-49,228,271` (sole production caller) and two test modules by name, with the expected effect (none today; a loud `UnsupportedStationError` replaces the silent `:328` filter for any caller passing an out-of-allow-list station in future). |
| MINOR c2 — `CombinedDraw`/`combine_station_day` signatures unread | YES. §6b.3 quotes the real signature (`settlement/current_rung_hold_v2.py:298`), the `CombinedDraw` field set (`:195-222`), and the four raise conditions (`:318-336`), each now caught and reported as `NO_PROPOSAL` (C15) rather than left to abort the run. |
| MINOR (both reviewers) — no alerting independent of the host unit's failed state | Correctly recorded as a **knowing, reasoned non-take** rather than silently dropped: 10b rides AUD-09b's wrapper and inherits its alerting; adding a second path would duplicate AUD-08b/AUD-14's mechanism for a generator whose expected daily output is `NO_PROPOSAL`. This is a defensible scope call, not an unresolved defect — see scoring note below. |

No round-2 acceptance is falsely claimed.

## Claims verified this round (fresh read against current source)

| Ref | Claim | Result |
|---|---|---|
| §6a all six `SUPPORTED_STATIONS` occurrences in `composition.py` (`:45,319,328,381,448,565`) and their dispositions | CONFIRMED against a fresh read of the full function bodies: `resolve_station_instrument_ids` (`:297-372`, `buckets` at `:318-320`, filter at `:328`), `_zero_instruments_message` (`:375-384`), `build_current_rung_hold_strategies` (`:424-470`, guard at `:444`, loop at `:448`), `build_continuous_rung_hold_strategies` (`:488-596`, guard at `:544`, loop at `:565`). Every disposition in §6's table matches the code exactly, including that `resolve_station_instrument_ids` and `_zero_instruments_message` already take the mapping as a parameter, so the narrowing is a local edit as claimed, not a signature change. |
| §3.5/§6 zero-instrument-guard hazard and its fix | CONFIRMED: `resolved = {station: tuple(ids) for station, ids in buckets.items()}` is keyed exactly by `buckets`' keys (`:318-320`), and the guard at `:444`/`:544` iterates `resolved.values()` — so narrowing `:319`'s bucket keys to the composable set is what makes the guard sound, exactly as claimed. |
| §6b.2 `C-VALIDITY`/`params_match` grounding | CONFIRMED against `config.py:226` and `deploy/families/pm_us_crh_v4.json` directly this round. |

## Defects

None found. All three round-2 MATERIAL defects are genuinely closed and independently re-verified against source. The specific question posed to this review — whether `C-PAIRED`'s `INERT` disposition leaves the replay output honest and usable, or misleading — resolves cleanly in favour of honest-and-usable: `INERT` is a distinct third value from `true`/`false`, it is never silently defaulted to `false` (which would misreport "the challenger lost" when no challenger comparison was even possible), it is accompanied by a named, owned blocking dependency rather than a vague "TODO", and C14 makes it structurally impossible for a run containing it to emit a `PROPOSAL` — so the mechanism cannot be gamed by an implementer who leaves `C-PAIRED` inert forever. The mechanism counts (trial/fill/refusal statistics) remain legible and usable independent of `C-PAIRED`'s state, and `C-VALIDITY`'s `params_match` clause independently blocks any edge claim from a row produced under the wrong fee coefficient. This is the correct way to represent "cannot currently evaluate" in a promotion gate.

## Strengths (credited)

10a is a complete, evidenced defect fix: six sites derived by a reproducible grep, each with a stated disposition, the zero-instrument guard made sound by narrowing its domain rather than bolting on a second check, and a golden byte-identity pin plus mutation evidence as the regression barrier. 10b never builds parallel architecture — the proposal is the existing manifest schema emitted as a draft, and `load_family_manifest`'s own `allow_draft=False` refusal is reused as the safety property. Both strategy-lead blockers (criteria transfer from a closed forecast family; whether MECHANISM_ONLY may feed a criterion) are kept explicit and score-uncapping rather than disguised as design decisions — this is exactly the rubric's "operator/strategy-lead decisions surfaced as BLOCKERS" requirement, done correctly. The content-hash idempotency scheme is a real, testable property.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 10a closes REG-1 across all six sites and closes the hole it would have opened; 10b's criteria set has a producer or a named INERT/absent-input behaviour for every predicate, and G-07's honest boundary (promotion is a human decision on a machine-checked proposal, not yet a machine-checked PROPOSAL) is stated, not hidden. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I re-opened this round (six composition.py sites, the guard, the fee-coefficient divergence, `CombinedDraw`/`combine_station_day`) is exact. |
| Implementation specificity and feasibility | 15 | 15 | Per-site dispositions, non-`app` caller effects, the serialiser, the layer contract (now with the working flag), content-hash scheme, per-predicate artefact bindings, and `C-ESTIMATOR`'s real input type are all decided to a buildable level. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C16 are objective; C4/C10 are attainable as written; C5/C6 cover the silent-halt class with a real test target; C14/C15/C16 close the round-2 gaps with concrete, RED-testable assertions. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Three hard refusals, contradiction ordering (`C-KILL` first), per-predicate absent-input behaviour replacing an absurd blanket rule, `combine_station_day`'s four refusals caught and reported, content-hash idempotency, read-only posture. The lack of independent alerting is a reasoned, stated scope decision (rides AUD-09b's inherited alerting, avoids duplicating AUD-08b/AUD-14) rather than an unaddressed gap — full marks are appropriate because the rubric asks for failure handling that is genuinely reasoned, and this is. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; the correctness-vs-return distinction is stated explicitly; both strategy-lead blockers kept verbatim; the AUD-09 build dependency is named with an owner; H2 declined without residue; arming/caps/NO-SEND untouched. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers

- **BLOCKER (strategy lead, real, correctly retained, does not cap this plan's score):** whether R5-7/R5-8 (written for the closed `pm_us_crh_fc_v1` forecast family) transfer to a `continuous_rung_hold` family, and what champion/challenger means at admissible live n = 0. `SOURCE=FORECAST_FAMILY_R5` tagging keeps the mechanism buildable; correctness awaits the ruling.
- **BLOCKER (strategy lead):** whether a `MECHANISM_ONLY` or `params_match=false` row may ever feed a promotion criterion — `C-VALIDITY`'s "no" default is conservative and correctly surfaced as a default, not decided here.
- **BLOCKER (build, named, owner stated, mirrored in AUD-09 §12):** `C-PAIRED` cannot evaluate until the driver gains a `--family-manifest` flag; excluded from this item's scope by design.
- **BLOCKER (operator):** arming, live-trading enablement, the two reserved caps — untouched by this item; no violation found.
