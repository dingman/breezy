# AUD-01 — Round 3 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
SHA256: 2a1ac1b140029d03c10e8d10138ad266cedc0263ebbb69d3701bd7b8fc7b6e67
Round: 3
Reviewer: prediction-market-reviewer (blind — no other reviewer's output consulted)

## Claims verified against source (this round, independent re-check)

- `decision.py:120-148` REFUSAL_REASONS frozenset, `__all__` entry at `:107` ("REFUSAL_REASONS," inside the `__all__` list opening `:106`) — CONFIRMED, exact.
- `Refuse.__post_init__` at `:239-242` (validates `reason in REFUSAL_REASONS`) — CONFIRMED.
- `_evaluate_no_side` `:425-449`; bid/bid_size executability check `:436-437`; `P_HOLD_UPPER.get(key)` at `:440` — CONFIRMED, exact, and the plan's proposed gate placement (after `:437`, before `:440`) is achievable without reordering any other branch.
- `archive_table.py:287` `P_HOLD_UPPER` — CONFIRMED present, consumed only by `monitor_evidence.py` and `decision.py` (2 callers, matches plan's "no other consumer" implication).
- `composition.py::_station_config` (`:387-421`) threads exactly ONE manifest-derived field, `required_fee_coefficient` — CONFIRMED verbatim; no other `CurrentRungHoldConfig` field is manifest-settable through this path today.
- `family_manifest.py` `_REQUIRED_KEYS` `:96-111`, `_OPTIONAL_KEYS` `:125` (`{"exit_rule","terminal_climate_day"}`), `load_family_manifest` `:211-236`, exact unknown-key exception text `f"{path}: unknown key(s): {sorted(unknown)}"` at `:236` — CONFIRMED byte-exact. `no_side_calibration_gate_cleared` is not a member of either set today, so §7 step 7a (schema-membership) and step 7b (adversarial construction against the real, unmodified `load_family_manifest`) are both executable exactly as specified, with zero production-code change required to pass.
- HUNT-1 characterization: re-checked `docs/core/PROGRESS.md:51` and `DECISION_FUNNEL_2026-09-20.md:98` this round — HUNT-1 is CRIT/open, "de-prioritised" not "moot," matching the plan's §3/§5/§12 text exactly.

No claim in Revision 3 was found to be inaccurate, stale, or unverifiable against current source. This is the fourth independent full re-verification of this plan's load-bearing citations (round 1 x2, round 2 x2, this round), and every one converges on the same source facts.

## Defects found this round

None, MATERIAL or MINOR. The round-2 mle-reviewer's MATERIAL finding (§7 step 7's Revision 2 test was executable but not provable-by-construction against future schema drift) is fixed correctly: §7 steps 7a/7b now pin both the schema-membership invariant (fails the instant `_OPTIONAL_KEYS` is ever widened) and the runtime behaviour (an adversarial payload is refused by the real, unmodified validator today). Both are independently re-verified against source this round, not merely carried over from the plan's own self-report.

Nothing regressed relative to Revision 2: the NO-side-only scope, the fail-closed default, the observability wiring (§6.5, `RefusalWatch._conditions` iterates `self._counter.counts`, no fixed/closed set — re-confirmed this round via the same reasoning as round 2, no source change since), and the AUD-01a/AUD-01b/HUNT-1/AUD-02-A1 goal-state disposition in §3 are all intact and consistent with AUD-02's own Revision 3 text.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — G-01's goal state is correctly disposed across AUD-01a/AUD-01b/HUNT-1/AUD-02-A1 with no overclaim; the sibling-family (`pm_us_crh_v2`/`pm_us_crh_cont`) exposure gap remains named-open, which both prior rounds' reviewers agreed is acceptable (not currently live, so not a live-money gap today) — not a fixable defect in this plan's own scope.
- Technical correctness and evidence grounding: 20/20 — every load-bearing citation independently re-verified this round, byte-exact.
- Implementation specificity and feasibility: 15/15 — the arming path, the gate placement, and both 7a/7b tests are fully specified and executable against real, unmodified source with zero implementation ambiguity left to the implementer beyond exact test file naming (explicitly acknowledged, immaterial).
- Acceptance criteria and validation quality: 20/20 — the RED test suite now covers: outcome (Refuse), non-consultation (spy on `P_HOLD_UPPER.get`), schema-membership (7a), and adversarial runtime behaviour (7b) — closing every defect class found across three rounds of review with no residual gap.
- Autonomous operation, failure handling, recovery: 15/15 — pure function, zero I/O, fail-closed default; unchanged and still correct.
- Portfolio alignment, scope, dependencies: 10/10 — HUNT-1 and AUD-02/A1 scope boundaries stated correctly and consistently with AUD-02's own Revision 3.

## Total: 100/100

## Required changes to reach 100

None. No material defect found this round.

## Blockers

None new. The plan itself correctly names its own inherent blockers as out of its scope: (1) the strategy-lead A1 ruling on `pm_us_crh_v4`'s broader disposition (owned by AUD-02, not decided here), (2) whether sibling families share this NO-side exposure (named open, not required to close this item, since only `pm_us_crh_v4` is currently live).
