# AUD-02 review — round 1 — prediction-market-reviewer

Plan: AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 4009b3215d532993e77504ddc7f76e85fb1b277359d07a0af39285b1e6452f5d
Round: 1
Reviewer: prediction-market-reviewer (blind, independent)

## Claims verified

- WP-B0 DONE, `f97c26f` — CONFIRMED via `git log`/`git show`; commit message matches plan's characterization exactly (alert egress, webhook delivery proven with a real loopback TLS server).
- WP-R1 DONE, `6aa9d92`/`e83fc5c` — CONFIRMED; the second commit is precisely the fix the plan describes (zero-evaluation false page on MDW, gated on tick count).
- `POST_FORECAST_PHASE_2026-09-20.md` A0/A1 content — CONFIRMED: A1's options (i/ii/iii), the "n reset to 0 per L-34" class-C requirement, and the "if A0 cannot produce [a CI-excluding-zero edge], (iii) is abandoned by default and (ii) is the answer" language are present verbatim, matching the plan's citations.
- C-branch 0.25/station-day qualifying-rate gate — CONFIRMED at `POST_FORECAST_PHASE_2026-09-20.md` line 286 ("< 0.25/station-day — 2× ABOVE the measured rate") and line 389.
- PROGRESS.md WP-R1 entry staleness claim — CONFIRMED: `PROGRESS.md:119` reads "Fix (not yet applied)" though `e83fc5c` landed the fix same-day (09-20).
- L-34 header — CONFIRMED at `LESSONS.md:1290`, correctly the "trial's trigger is pinned" lesson, not the "class-C" number the coordinator note in `DECISION_FUNNEL` itself flags as a misquote — AUD-02's own use of L-34 (re: n reset) is the correct citation, distinct from that misquote.

## Assessment against the challenge questions

- **Goal-state reachability, not a bare "adopt the other plan":** the plan does more than adopt — it folds in a substantive, independently-verified finding (the calibration-defect result) as a widened A1 precondition, and that widened precondition already carries a pre-committed default ((ii) STOP TRADING) if no independent edge estimate can be produced. This satisfies "reach the goal state" in the sense the brief requires: the programme is not left in open-ended limbo, it has a named default disposition if the harder bar is not cleared. Correctly scoped as a status/fold-in item, not a design proposal.
- **Blocker surfaced, not decided:** A1 is correctly named as a strategy-lead ruling, consistent with the repo's own governance model (operator/strategy-lead decisions must be surfaced, not decided by a build plan).

## Defects

- **MINOR** — §11/§12: no escalation or expiry mechanism is proposed for the A1 blocker itself. The repo has already paid concretely (per this same evidence chain) for exactly this failure shape — a correct finding sitting undelivered/unactioned (WP-B0's own justification: "every alert this system has ever emitted went to a log file nobody reads"; the 3-day fee halt, the 11-hour permit lapse). A named BLOCKER with no cadence or reminder mechanism risks the same rot. Recommend citing AUD-03's digest (once shipped) as the natural vehicle to keep A1's open status visible, or naming an explicit re-audit trigger (e.g., N days elapsed).
- **MINOR** — §12: flags but does not resolve whether `bcb82d6`/`e3e8ac6` register `pm_us_crh_v4` consistent with A1(iii)'s own invariants (A-9 in the base plan). Correctly named as open rather than asserted either way — acceptable for a status/fold-in item, but worth a one-line pointer to who owns closing it (presumably A1 itself, on ruling (iii)).

No MATERIAL defect found: citations verified accurate, scope correctly bounded, default-disposition logic is present and sound, and the plan does not attempt to decide what is legitimately reserved to a strategy-lead ruling.

## Per-criterion points

- Fidelity to audit gap and completeness: 18/20 — correctly scoped; does not re-verify every downstream work package line-by-line (self-disclosed, reasonable given this is a status item over an already-peer-reviewed plan).
- Technical correctness and evidence grounding: 19/20 — every checked citation accurate, including the two commit-verified DONE claims and the exact A0/A1/C-gate text.
- Implementation specificity and feasibility: 14/15 — Amendment C text is fully specified and pasteable; appropriately lower ceiling for a documentation item.
- Acceptance criteria and validation quality: 16/20 — concrete for the documentation deliverable; the real acceptance (A1 ruling) is outside this plan's power, correctly acknowledged, but no escalation mechanism weakens the "the ruling actually happens" half.
- Autonomous operation, failure handling, recovery: 13/15 — fail-closed default correctly identified as acceptable indefinitely; no proposal for surfacing indefinite-limbo risk (ties to the MINOR above).
- Portfolio alignment, scope, dependencies: 10/10 — explicit, correct dependency on AUD-01a; correctly refuses to re-run the closed hunt; correctly does not decide A1.

**Total: 90/100.**

## Required changes to reach 100

1. Name an explicit mechanism (cadence, reminder, or dependency on AUD-03's digest) to prevent the A1 blocker from rotting silently, given this repo's own prior cost from exactly this failure shape.
2. Name an owner/trigger for resolving the open `bcb82d6`/`e3e8ac6` A-9-consistency question (can defer to A1 itself, but state that explicitly).

## Blockers

- **A1 itself** (strategy-lead ruling) — correctly named by the plan as outside its own authority; this is the plan's own stated BLOCKER, not a defect in the plan.
- **Operator budget ceiling** for any eventual re-arming — correctly named and correctly not touched by this plan.
