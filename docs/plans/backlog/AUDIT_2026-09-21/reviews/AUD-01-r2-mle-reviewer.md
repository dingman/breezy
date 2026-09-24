# AUD-01 — Round 2 review (mle-reviewer, ML/production-engineering lens)

Plan: AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
sha256: 1957d72115986011ca100eba778243efabbe2911f3f8c7afa9259dddd5b0580e
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 disposition check (both accepted defects actually fixed?)

- **mle-reviewer round-1 MATERIAL (arming path misdescribed, §6.3/§9):**
  Re-verified directly against current source this round.
  `composition.py::_station_config` (`:387-421`) — CONFIRMED verbatim: threads
  exactly one manifest field, `required_fee_coefficient`; every other
  `CurrentRungHoldConfig` field is a literal/constant. `family_manifest.py`
  `_REQUIRED_KEYS`/`_OPTIONAL_KEYS` (`:96-125`) — CONFIRMED, `_OPTIONAL_KEYS =
  {"exit_rule", "terminal_climate_day"}`, no calibration-gate slot.
  `load_family_manifest` (`:228-236`) — CONFIRMED: `unknown = keys -
  _REQUIRED_KEYS - _OPTIONAL_KEYS; if unknown: raise`. The rewritten §6.3
  correctly names the real arming path (a `composition.py` code change only).
  **Fix CONFIRMED, not merely claimed.**
- **prediction-market-reviewer round-1 MATERIAL (HUNT-1 "moot"):** not this
  lens's independent check to re-litigate in depth, but the rewritten §3/§5/
  §12 text ("HUNT-1 is NOT moot... remains open, tracked in PROGRESS.md")
  reads as a plain-text correction consistent with the reviewer's required
  change; no source contradiction found in this round's pass.
- **REFUSAL_REASONS citation fix:** re-verified directly —
  `decision.py:106-107` is the `__all__` list with `"REFUSAL_REASONS"` as its
  first entry landing at line 107; `decision.py:120` opens the frozenset
  literal. CONFIRMED exact, matches the plan's corrected citation.

## New-defect pass on the revision itself (coordinator's specific check)

**The rewritten §9 failure-case test is executable, but weaker than its own
"provable by construction" framing claims — a genuine, not cosmetic, gap.**

§9 (and §7 step 7) describe the failure-case test as: run
`load_family_manifest` + `_station_config` against every currently-registered
family manifest and assert the resulting `CurrentRungHoldConfig.
no_side_calibration_gate_cleared == False`. This test:

- **Is executable and non-vacuous in a narrow sense** — it can genuinely fail
  (e.g., a typo flips the dataclass default to `True`, or a future edit to
  `_station_config` accidentally threads the flag from an unrelated source).
  So it is not vacuous in the trivial sense the brief warns against.
- **Does NOT prove the invariant it is offered as proof of.** The claim is
  "no manifest field can set it... provable by construction (no manifest key
  maps to it)." But iterating over the CURRENT set of registered manifest
  JSON files only shows that none of today's files happen to carry this key
  — because none can, today, since the schema rejects unknown keys. If a
  future change ever added `no_side_calibration_gate_cleared` to
  `_OPTIONAL_KEYS` AND `_station_config` were changed to thread it (exactly
  the scenario the safety design is supposed to force through deliberate
  review), this same test would keep passing indefinitely, for as long as no
  currently-registered manifest file happens to set the key `true` — giving
  false confidence that the "no manifest path exists" invariant still holds
  when it no longer does. The test verifies "current manifests don't turn it
  on," not "the schema cannot turn it on."
- §7 step 7's own parenthetical is closer to the right test — "the field is
  absent from `_OPTIONAL_KEYS` and `_station_config` never reads it from the
  manifest" — but that stronger, schema-level assertion is not what §9's
  failure-case prose actually specifies, and §9 explicitly and by name
  REJECTS the alternative that would make this genuinely non-vacuous ("not by
  an attempted-and-rejected manifest edit as the round-1 draft incorrectly
  described"). That original round-1 direction (constructing a manifest
  payload with the key injected and asserting `load_family_manifest` raises
  `FamilyManifestValidationError` for an unknown key) is not merely
  executable, it is the test that actually proves the schema-level
  invariant, behaviorally, against the real validation path — and it was
  discarded in this revision in favor of a weaker one.

This is the exact class of gap the round-1 mle-reviewer flagged for §9 (an
untestable/mis-scoped failure-case assertion), reappearing one level down: the
revision fixed the factual claim (no manifest path exists TODAY) but did not
fix the TEST to actually pin that invariant against future drift, which is
the whole point of a "provable by construction" safety-gate test.

**Classification: MATERIAL.** This is the single most safety-critical
mechanism in the plan (the arming/rollback control for a fail-closed
NO-side gate); a test that reads as ironclad but is actually silent to the
one future change it exists to catch is a real production-ML risk (a
calibration-gate arming path this repo would not learn had opened until a
live fill happened).

**Required change:** rewrite the §9/§7-step-7 failure case as BOTH:
1. A direct schema-membership assertion:
   `"no_side_calibration_gate_cleared" not in
   (family_manifest._REQUIRED_KEYS | family_manifest._OPTIONAL_KEYS)` —
   this fails the instant the schema is ever widened to accept it, forcing a
   deliberate test update at exactly the point the safety design wants
   friction.
2. An adversarial construction test: build a manifest JSON payload (a copy of
   any currently-registered manifest's fields) with
   `"no_side_calibration_gate_cleared": true` injected, feed it to
   `load_family_manifest`, and assert it raises
   `FamilyManifestValidationError` ("unknown key(s)") — this is the
   behaviorally-grounded version of the round-1 draft's original intent,
   done correctly against the real validation function instead of against
   unmodified files.
The existing "run real manifests through the pipeline, assert False" check
may remain as a secondary regression guard, but must not be the sole or
primary proof of the invariant.

## Other claims re-verified this round

- `decision.py:399-404` (`_finalize_take`'s break-even test,
  `p_bound > break_even`) — not itself part of AUD-01's proposed change, but
  re-confirmed exact (relevant since AUD-01a's gate must sit upstream of this
  check); no discrepancy found.
- `_evaluate_no_side` gate placement (`:436-437`/`:440`, bid/bid_size check
  before `P_HOLD_UPPER.get`) — unaffected by this revision's changes,
  re-confirmed present as before.
- No other new defect found in the revised §3/§5/§12 HUNT-1 text, the §6/§7
  RED-test ordering, or the rollback/observability sections (§10) — these
  read as correctly grounded and internally consistent.

## Per-criterion points (out of the brief's rubric: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — the G-01 goal-state
  reconciliation (§3) and HUNT-1 correction are complete and consistent; no
  gap found this round.
- Technical correctness and evidence grounding: 20/20 — every citation
  checked (composition.py wiring, family_manifest.py schema,
  REFUSAL_REASONS line numbers, decision.py gate order) is exact against
  current source.
- Implementation specificity and feasibility: 13/15 — the gate placement
  itself remains precise and implementable; docked 2 points because the
  failure-case test's actual mechanics (§9/§7 step 7) are specified in a way
  that would lead a literal implementer to ship a test weaker than the
  safety property it claims to prove.
- Acceptance criteria and validation quality: 16/20 — docked here rather than
  purely under implementation specificity, since this is precisely an
  acceptance-criteria-strength defect: the stated proof ("provable by
  construction") overstates what the specified test actually validates.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected; pure
  function, fail-closed default, no I/O, sound rollback story (reverting the
  diff, not the flag, is the recovery path).
- Portfolio alignment, scope, dependencies: 10/10 — unaffected; scope
  attribution across AUD-01a/AUD-01b/HUNT-1/AUD-02's A1 remains correct and
  non-overlapping.

**Total: 94/100.**

## Required changes to reach 100

1. Rewrite the §9/§7-step-7 failure-case test per the "Required change" above
   (schema-membership assertion + adversarial injected-key construction
   test), and correct §9's prose, which currently explicitly disclaims the
   adversarial-construction approach that would make the invariant actually
   non-vacuous.

## Blockers

None requiring operator/strategy-lead input from this lens. The MATERIAL
defect above is a plan-authoring/test-design correction, resolvable by the
implementer (or a further plan revision) without any ruling. The plan's own
named BLOCKER (§12, AUD-02's A1 strategy-lead ruling) remains correctly
scoped outside this plan.
