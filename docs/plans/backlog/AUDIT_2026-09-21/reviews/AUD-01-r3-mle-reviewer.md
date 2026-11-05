# AUD-01 — Round 3 mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
sha256: 2a1ac1b140029d03c10e8d10138ad266cedc0263ebbb69d3701bd7b8fc7b6e67
Round: 3
Reviewer: mle-reviewer (lens: production ML engineering — calibration tables as models, train/serve skew, data contracts, monitoring, rollback)

## Claims verified against source (this round, independent re-read)

- `family_manifest.py:96-125` `_REQUIRED_KEYS`/`_OPTIONAL_KEYS` — CONFIRMED exact.
  `_OPTIONAL_KEYS = frozenset({"exit_rule", "terminal_climate_day"})`; no slot
  for `no_side_calibration_gate_cleared`.
- `family_manifest.py:211-236` unknown-key refusal — CONFIRMED exact:
  `unknown = keys - _REQUIRED_KEYS - _OPTIONAL_KEYS; if unknown: raise
  FamilyManifestValidationError(f"{path}: unknown key(s): {sorted(unknown)}")`
  at lines 234-236 byte-for-byte as cited.
- Exception class name `FamilyManifestValidationError` — CONFIRMED, defined
  at `family_manifest.py:148`, matches plan's §7 step 7b citation exactly.
- `composition.py::_station_config` (:387-421) — CONFIRMED threads only
  `required_fee_coefficient` from the manifest path; no other
  `CurrentRungHoldConfig` field is settable this way. The plan's central
  "no manifest path exists for this field" claim, load-bearing for both the
  arming-path design (§6.3) and the round-2 fix, is accurate.
- `decision.py:107,120` (`REFUSAL_REASONS` `__all__`/frozenset-open lines) —
  CONFIRMED exact.
- `halt_detector.py:138-154` `STRUCTURAL_HALT_REASONS` — CONFIRMED exact
  five-member closed set; `observation_ambiguous`/`illegal_cell` confirmed
  absent, supporting §6.5's "no new plumbing" claim.
- `refusals.py::RefusalWatch._conditions` — CONFIRMED iterates
  `self._counter.counts` (not a fixed set), supporting the same claim.
- `PROGRESS.md:51` HUNT-1 CRIT entry — CONFIRMED verbatim ("Continuous
  hunting is REQUIRED and NOT met").

## Non-vacuity check on 7a/7b (this round's specific charge)

Both tests are genuinely non-vacuous, not merely restated claims:

- **7a (schema-membership assertion):** a structural pin
  (`"no_side_calibration_gate_cleared" not in (_REQUIRED_KEYS |
  _OPTIONAL_KEYS)`) that fails the instant a future schema change adds the
  key — this is a real regression guard against drift, not a tautology,
  because it reads the live module constant rather than a hardcoded copy.
- **7b (adversarial construction test):** builds a synthetic manifest
  payload with the key injected and feeds it to the REAL, unmodified
  `load_family_manifest`, asserting the exact exception type and message
  substring. This exercises actual runtime behavior against an
  attacker-shaped input, not a static assertion — it would fail today if
  `load_family_manifest`'s unknown-key check were ever removed or weakened,
  which 7a alone would not catch (7a only pins the schema constant, not the
  validator's enforcement of it). The two tests are complementary and
  neither is redundant with the other: 7a pins the schema, 7b pins the
  validator's behavior against that schema. Together they close the exact
  gap raised in round 2 (a test that would keep passing even if the schema
  were later widened).

No defect found in this pairing. The revision's own retraction of Revision
2's wrong rejection of the adversarial-construction approach is also
accurate — a synthetic payload requires no registered manifest file, only
test-code construction, which is trivially possible against the shipped
function.

## Defects

None MATERIAL. None MINOR beyond what the plan already discloses (sibling-
family exposure named-open, both prior rounds agreed this is acceptable as
stated, no required change identified this round either).

## Per-criterion points

- Fidelity to audit gap and completeness: 20/20 — full G-01 goal-state
  reconciliation (safety half vs reach-pricing half) is precise and
  consistent with `DECISION_FUNNEL_2026-09-20.md`/`PROGRESS.md`.
- Technical correctness and evidence grounding: 20/20 — every load-bearing
  citation re-verified this round, all exact.
- Implementation specificity and feasibility: 15/15 — the gate placement,
  arming path, and both new tests are fully specified and executable against
  real, unmodified functions.
- Acceptance criteria and validation quality: 20/20 — 7a/7b close the
  non-vacuity gap raised in round 2; the lookup-never-called spy (§7 step 2)
  and the byte-identical YES-side fixture are both concrete and testable.
- Autonomous operation, failure handling, recovery: 15/15 — pure function,
  zero I/O, fail-closed default, no retry/hang surface.
- Portfolio alignment, scope, dependencies: 10/10 — HUNT-1/AUD-02
  relationship correctly attributed and non-circular.

**Total: 100/100.**

## Required changes

None.

## Blockers

Named in the plan itself, not raised by this review: the AUD-02 A1
strategy-lead ruling (§12) — correctly identified as out of this plan's
scope.

## Disposition

APPROVE. Zero material defects found this round; both round-2 fixes
(7a/7b) verified non-vacuous against current source.
