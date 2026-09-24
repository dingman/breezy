# AUD-19 round 1 review — trading-bot-architect

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: b57f9531297b8400a598b73323b668c28d662c965219bd42bf86f1ad487225d9
Round: 1

## Claims verified
- Ruling Q1 item 3 shape quoted verbatim in §6 A1 → CONFIRMED against RULING file :164, exact match.
- Ruling Q4 minimum scope ("thread at minimum required_fee_coefficient... :932") → CONFIRMED :534-538, plan matches exactly (renamed taker_fee_coefficient→required_fee_coefficient per config.py:226).
- CurrentRungHoldConfig fields vs pm_us_crh_v4.json fields (config.py:161-237 verified via codegraph) → only required_fee_coefficient genuinely varies at runtime; boundary/density artefact shas feed the offline archive-table build (archive_table_pin, a fixed constant), not this config — threading only the fee is sufficient, no other silently-defaulted engine param found.
- Import-linter layering (pyproject.toml:68-92) → CONFIRMED: runtime > persistence is a legal downward edge; `scripts/` is outside the `breezy` container, so lint-imports does not constrain it, as claimed.
- §9 claim "after AUD-19 [lands], AUD-09's rows become family-scoped with no code change on its side" → REFUTED. AUD-09 §6b.2 items 3/5 (AUD-09 plan :500-519) describe AUD-09's runner independently calling `load_family_manifest` itself and stamping `engine_required_fee_coefficient` from the driver's known class default — it never invokes `current_rung_hold_paper_replay.py --family-manifest` nor reads AUD-19's `family_params.json` sidecar anywhere in its text. AUD-10 §12 (:908-915) mirrors this: "Owner: AUD-19 ... this plan asserts nothing about its content." Neither consumer plan specifies who wires the new flag into AUD-09's subprocess invocation or who parses the sidecar.

## Defects
- **MATERIAL** — Consumer contract not satisfiable as drafted. §9's "no code change on AUD-09's side" and §12's sidecar-consumption assumption ("AUD-09's runner reads the C6 sidecar... neither item changes") are unverified against AUD-09's actual text and contradicted by it: AUD-09 computes provenance by loading the manifest itself, not by invoking this driver's flag. Without a stated caller change in AUD-09 (or an explicit new increment here), `params_match` stays False forever even after 19b lands — `C-PAIRED`/`C-VALIDITY` never actually unblock, defeating the item's own §11 rationale ("a precondition for ROI"). **Required change:** either (a) AUD-19 states explicitly, and AUD-09 is amended to confirm, that AUD-09's scheduled runner will invoke the driver with `--family-manifest` and read `family_params.json` (naming the exact call-site change), or (b) AUD-19 drops the "no code change on AUD-09's side" claim and records the wiring as an open, owned follow-up rather than an assumed consequence.
- **MINOR** — C6's sidecar key set includes `exit_rule`, absent from AUD-09's own row schema (AUD-09 §8 fields list, plan :698-700); harmless since AUD-09 doesn't consume the sidecar today, but should be reconciled once (a) above is resolved.

## Per-criterion points
- Fidelity to audit gap and completeness: 18/20 (Q1+Q4 both covered faithfully; not higher due to unresolved consumer-wiring gap above)
- Technical correctness and evidence grounding: 17/20 (all file:line citations verified true; -3 for the false §9 "no code change" claim)
- Implementation specificity and feasibility: 13/15 (D1/D2 well-reasoned; C2 sentinel verified against actual test D4)
- Acceptance criteria and validation quality: 15/20 (A1-A8 objective and testable in isolation; but no criterion proves the sidecar is ever actually read by anything — the plan's own §12 admits this, and the contract gap above means A6 is not sufficient evidence the goal state is reached)
- Autonomous operation, failure handling and recovery: 13/15 (fail-closed throughout; no exit-code vocabulary, deliberately, minor)
- Portfolio objective alignment, scope and dependencies: 8/10 (honest zero-ROI framing; scope justified)

**Total: 84/100**

## Blockers
None requiring operator/strategy ruling — this is a build-item cross-plan wiring gap resolvable by editing AUD-19 (and/or AUD-09) text, not a ruling.
