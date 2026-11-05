# AUD-01 review — round 2 — prediction-market-reviewer

Plan: AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
sha256: 1957d72115986011ca100eba778243efabbe2911f3f8c7afa9259dddd5b0580e
Round: 2
Reviewer: prediction-market-reviewer (blind, independent)

## §13 review-history verification (round-1 defects actually fixed, not just claimed)

- mle-reviewer round-1 MATERIAL (arming path refuted): CONFIRMED FIXED. Re-verified directly:
  `composition.py::_station_config` (:387-421) threads only `required_fee_coefficient`
  (verbatim: builds `CurrentRungHoldConfig` with either no extra kwarg or
  `required_fee_coefficient=required_fee_coefficient` only). `family_manifest.py`
  `_OPTIONAL_KEYS` (:125) = `frozenset({"exit_rule", "terminal_climate_day"})` — no
  calibration-gate slot; `load_family_manifest` (:229-236) computes
  `unknown = keys - _REQUIRED_KEYS - _OPTIONAL_KEYS`, i.e. an unrecognised key is rejected.
  §6.3's rewritten claim ("no manifest path exists; arming requires a composition.py code
  change") is TRUE against current source.
- prediction-market-reviewer round-1 MATERIAL (HUNT-1 "moot"): CONFIRMED FIXED.
  `PROGRESS.md:51` re-read this round: HUNT-1 is CRIT, "Continuous hunting is REQUIRED and
  NOT met," supersedes WIN-1. `DECISION_FUNNEL_2026-09-20.md:98` re-read: "HUNT-1 stays open
  but is de-prioritised behind these two." The plan's §3/§5/§12 now state exactly this, with
  a new "goal state for G-01" paragraph (§3) explicitly attributing the reach-pricing half of
  G-01 to HUNT-1 (tracked, out of scope) + AUD-02's A1 ruling, never claiming AUD-01 closes
  either. Path through 01a/01b/HUNT-1/A1 is explicit, as required.
- prediction-market-reviewer round-1 MINOR (spy on lookup): CONFIRMED FIXED. §7 step 2 adds
  an explicit "never called" assertion via a spy/instrumented dict; §8's bullet 3 restates it
  as a required acceptance artefact.

## Claims verified this round (fresh, whole-plan pass)

- `decision.py:120` (`REFUSAL_REASONS` set literal opens) / `:107` (`__all__` entry) —
  CONFIRMED exact against current source (both lines re-read directly).
- `decision.py:291-302` `_is_legal_cell`, unconditional `width_code == 2` refusal, L-22
  citation — CONFIRMED; `LESSONS.md:1017` header text ("A safety primitive's exclusion must
  be unforgeable, not offered") matches the plan's paraphrase.
- `decision.py:425-449` `_evaluate_no_side`: `no_ask = 1 - bid`, `P_HOLD_UPPER.get(key)` at
  line 440, `p_miss_lower = 1 - p_hold_upper` at 441, fed into `_finalize_take` as `p_bound`
  — CONFIRMED verbatim, matches §6's proposed gate-placement citation exactly (immediately
  after the `:436-437` bid/bid_size check, before the `:440` lookup).
- `archive_table.py:287`, `P_HOLD_UPPER: Final[Mapping[...]] = (` — CONFIRMED opens at that
  exact line.
- `RefusalWatch._conditions` (`refusals.py:219-233`) iterates `self._counter.counts`, not a
  fixed reason set, with the module's own docstring confirming "no second, drifting list of
  reasons to keep in sync" — CONFIRMED; §6.5's "no new plumbing" claim holds.
- `halt_detector.py` `STRUCTURAL_HALT_REASONS` (`__all__` entry :88) is a distinct, closed
  set never including `observation_ambiguous`/`illegal_cell`/a calibration-gate reason by
  construction — CONFIRMED; §6.5's "not added to STRUCTURAL_HALT_REASONS" is consistent with
  current source and does not silently create a new halt page.
- `PROGRESS.md:51` HUNT-1 CRIT / `DECISION_FUNNEL_2026-09-20.md:98` de-prioritised-not-moot
  — CONFIRMED (see above).
- Domain-reviewer NO-side finding (233/240 cells, mean +0.094 against `P_HOLD_UPPER`,
  "UNSALVAGEABLE, not merely miscalibrated") — CONFIRMED verbatim in
  `DECISION_FUNNEL_2026-09-20.md`'s final sections ("Domain review verdict (returned)",
  "NO-side magnitude: the DOMAIN REVIEWER'S number stands").

## Defects

None found, MATERIAL or MINOR, after independently re-verifying every load-bearing citation
against current source (`decision.py`, `archive_table.py`, `composition.py`,
`family_manifest.py`, `refusals.py`, `halt_detector.py`, `PROGRESS.md`,
`DECISION_FUNNEL_2026-09-20.md`) and re-tracing the two round-1 corrections. The revision
does not introduce any new defect: the rewritten §6.3 arming path and §9 failure-case test
are both provable by construction against the actual, closed `_OPTIONAL_KEYS` set (no
manifest field maps to the new gate flag), and the HUNT-1 reconciliation is accurate and
does not overstate what AUD-01 itself closes.

The two items the plan itself holds back one point for (exact new test-file names left to
implementer judgement; sibling-family `pm_us_crh_v2`/`pm_us_crh_cont` exposure named open)
are genuine, honestly-scoped, non-required items — not defects. `pm_us_crh_v4` is the only
currently-live family (`bcb82d6`), so the sibling-family gap is correctly non-blocking; test
file naming is routine implementer latitude, not a specification gap (the RED tests
themselves are fully specified by behaviour, at §7 steps 1-2/4/7).

## Per-criterion points

- Fidelity to audit gap and completeness: 20/20 — G-01's goal state is now explicitly
  reasoned through the union of AUD-01a/AUD-01b/HUNT-1/AUD-02's A1, with each piece's scope
  correctly bounded; no overclaim, no silent absorption of HUNT-1.
- Technical correctness and evidence grounding: 20/20 — every citation checked this round
  (11 distinct file:line references) matches current source exactly; both round-1 refuted
  claims are now correct and independently re-confirmed.
- Implementation specificity and feasibility: 15/15 — gate placement, refusal-reason
  addition, config field, and the real (code-only) arming path are all concrete and
  verified executable against current source; no design decision is left to the implementer.
- Acceptance criteria and validation quality: 20/20 — the lookup-never-called spy test and
  the provable-by-construction manifest-exposure test both close the round-1 gaps precisely
  and are independently testable.
- Autonomous operation, failure handling, recovery: 15/15 — pure function, fail-closed
  default, no I/O, explicit rollback story (revert-safe because the default is already the
  safe state); no live-money side effect on crash.
- Portfolio alignment, scope, dependencies: 10/10 — HUNT-1 and A1 are both correctly
  attributed to their true owners (PROGRESS.md CRIT item and AUD-02 respectively) rather
  than absorbed or dismissed; AUD-01a/AUD-01b's mutual independence is accurate.

**Total: 100/100.**

## Required changes to reach 100

None.

## Blockers

- Named, correctly scoped, not this plan's to resolve: AUD-02's A1 ruling (family
  disposition of `pm_us_crh_v4`'s YES side / retirement question) — strategy-lead call.
- HUNT-1 itself (window widening) remains a separate, open, operator-mandated CRIT item
  (`PROGRESS.md:51`) that this plan correctly does not attempt to close.

Neither blocker withholds any point from this plan's own score — both are accurately named
as out of scope rather than mischaracterized as resolved.
