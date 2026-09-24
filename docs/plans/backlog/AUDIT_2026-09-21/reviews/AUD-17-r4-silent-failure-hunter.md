# AUD-17 — Round 4 review (silent-failure-hunter, FINAL)

**Plan file:** AUD-17-operator-caps-proven-through-the-v4-live-composition.md
**SHA256:** ddb769bc1a5ec850859dca6ef04bee13448578fb81ff71022bc901b1fcbf2850
**Round:** 4 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source this session (focus: the precondition pin from §7 17a step 2a, per the coordinator's round-4 brief — "the precondition pin must be shown capable of failing")

| Claim | Status |
|---|---|
| `test_operator_control_assignment_scan.py` layer B = `files_naming_a_control()` (`:347-358`), a **byte-level literal census**: `needles = [name.encode("utf-8") for name in sorted(CONTROL_ENV_VAR_NAMES)]`, then `if any(needle in blob for needle in needles): naming.add(relative)` | CONFIRMED, exact line 347 |
| `CONTROL_ENV_VAR_NAMES` (`:90-92`) = `frozenset(operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS)` — the **env-var name strings themselves** (e.g. `MAX_POSITION_COST_USD_ENV_VAR: Final = "BREEZY_MAX_POSITION_COST_USD"`, `operator_controls.py:136`) | CONFIRMED |
| `CONTROL_CONSTANT_IDENTIFIERS` (`:99-104`) = the **Python identifier names** that hold those strings (derived by reflection over `vars(operator_controls)`) — a *different* string set from `CONTROL_ENV_VAR_NAMES` | CONFIRMED |
| `_mentions_control` (`:157-167`, layer A) checks `ast.Constant.value in CONTROL_ENV_VAR_NAMES` **or** `ast.Name.id in CONTROL_CONSTANT_IDENTIFIERS` — i.e. layer A's AST walk classifies a bare identifier reference (e.g. `MAX_POSITION_COST_USD_ENV_VAR` used in an f-string) as "naming a control" | CONFIRMED |
| `test_only_the_definition_module_names_an_operator_reserved_control` (`:610-620`) pins `files_naming_a_control() == {DEFINITION_MODULE, "operator.env.example"}` — an exact set | CONFIRMED, exact line 610 |

## MATERIAL defect this round — the precondition pin's failure mode is structurally mis-targeted, and §8's "capable of failing" requirement has no specified way to be met legitimately

The identifier `MAX_POSITION_COST_USD_ENV_VAR` (bytes: `MAX_POSITION_COST_USD_ENV_VAR`) does not contain, as a substring, the literal env-var-name string it holds (`BREEZY_MAX_POSITION_COST_USD`). Consequently `files_naming_a_control()` — a **pure byte-string census against `CONTROL_ENV_VAR_NAMES`**, not against `CONTROL_CONSTANT_IDENTIFIERS` — can **never** place a file that merely references the identifier (never spelling the literal env-var name) into its flagged set, *by construction*, independent of anything "layer B's tolerance" might mean. This is not an incidental implementation detail; it is the entire reason `tests/unit/operator_control_env.py` and the plan's own §6 assertion-2 design ("built from the constant **imported**... never from a literal") are structurally safe in the first place — the design deliberately avoids ever writing the literal string into source precisely so layer B's byte census cannot see it.

§7 step 2/2a and §8 item 2a nonetheless frame this as an **empirical, potentially-changing fact about layer B** ("Determine layer B's exact tolerance," "a restored tolerance would silently leave the per-position test running two-assertion forever," "fails loudly when layer B starts tolerating the imported-constant form"). But layer B was never *intolerant* of the identifier form to begin with — there is no plausible in-repo event that would make `files_naming_a_control()` start flagging a file that only references the identifier, **short of editing `files_naming_a_control()` itself to scan `CONTROL_CONSTANT_IDENTIFIERS` in addition to `CONTROL_ENV_VAR_NAMES`** — i.e., short of touching `test_operator_control_assignment_scan.py`, which §5 and §8 item 5 both forbid unconditionally (`git diff` must be empty on that file).

This creates a genuine bind on §8 item 2a's own requirement that the pin be "demonstrated capable of firing, not merely present," via a RED→GREEN transcript:
- If the RED-phase demonstration is produced by **actually editing** `files_naming_a_control()` (even temporarily, then reverting before the final commit), that is exactly the "amend the scan" repair §5 calls "the one repair forbidden," and a transcript produced that way is evidence of a rule violation during execution, not merely in the final diff.
- If instead the demonstration is produced by **monkeypatching** the imported `files_naming_a_control` symbol from inside the new test file for the duration of one RED-phase assertion (e.g. `monkeypatch.setattr(scan_module, "files_naming_a_control", lambda: {..., new_file_path})`) — a legitimate technique that touches no file under the scan's own `git diff` guard — the plan **never names this mechanism**. Nothing in §6, §7 step 2a, or §9 states that a monkeypatch-based inversion is the intended (or even an acceptable) way to satisfy "capable of firing." An implementer following the plan as written has no specified path to the required demonstration, and the two most obvious approaches are either forbidden or unspecified.
- Even granting a monkeypatch-based demonstration, it would prove that a **hypothetically modified** `files_naming_a_control` fails the pin — not that the pin's assertion, as actually written against the **real, unmodified** helper, is capable of failing under any reachable real-world state change. Since real-world tolerance of the identifier form by layer B is not a variable that can drift (it is fixed by `files_naming_a_control`'s literal-byte-census design, which the plan itself relies on as permanent), the pin's stated purpose — "fails loudly when layer B relaxes" — describes an event that cannot occur without the forbidden edit, making the underlying premise the pin was written to protect (round 3's "durable-by-default" concern) already permanently false rather than fixed.

This is exactly the brief's named risk (a detector that is trivially true / a vacuous test wearing the shape of a real one), now one level deeper than round 3's version of it: round 3 asked for *a* mechanism to prevent the fallback from being silently permanent; this revision supplied a mechanism whose own failure condition cannot be reached through any legitimate, in-scope action, which makes §8 item 2a's "demonstrated capable of firing" requirement either unsatisfiable as written or satisfiable only by an unspecified, unreviewed technique the plan never names.

**Required change — either of:**
1. Retarget the precondition pin at the thing that can actually drift: layer A's `_mentions_control`/`CONTROL_CONSTANT_IDENTIFIERS` classification is the correct site for "does the imported-constant style still count as naming a control," and the genuinely revisit-worthy question is whether **layer A's scan (`scan_control_assignments`), not layer B's byte census**, would ever flag the new test file's f-string reference — name that mechanism precisely (does `scan_control_assignments` walk f-string/`JoinedStr` nodes the way `_mentions_control` does, or only the specific assignment-shape call arguments enumerated in `_ENV_WRITE_CALLS`/`_ENV_READ_CALLS`/A6's callee list?) and build the pin against that, since layer A — unlike layer B — genuinely could start flagging a currently-tolerated shape if its own AST-walk scope is later widened without anyone reasoning about this test.
2. If layer B truly is the intended target, state explicitly, in the plan, the exact legitimate mechanism for the RED-phase "capable of firing" demonstration (a named monkeypatch pattern, with the scan module's `git diff`-empty guarantee stated as unaffected by it), so an implementer is not left to invent — or accidentally violate §5 while producing — the evidence §8 item 2a requires.

## Other attack points from the brief

- No other vacuous-test shape found in the ten named §7 17b tests; the ADMIT case and the per-position differential remain the two structurally load-bearing guards against a vacuous denial-only suite, and neither is contingent on the layer-B question above.
- The three-cause enforcement table (session-notional / daily-budget / per-position, with the per-position ceiling correctly raising a **plain** `LiveTradingPermissionError`) was not re-derived from source this session (already independently re-derived by two different reviewers in rounds 2 and 3 with matching results); no reason found to reopen it.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-16 closed as stated, third denial cause folded in; still correctly scoped as verification-only. Unaffected by the pin defect. |
| Technical correctness and evidence grounding | 20 | 17 | The three-cause table and gate ordering remain accurate. Deducted 3: the round-4 addition (the precondition pin) is built on a technically inaccurate premise about what `files_naming_a_control()` actually measures — a real evidence-grounding miss in the newest material, not a carried/acknowledged one. |
| Implementation specificity and feasibility | 15 | 11 | **MATERIAL** — §8 item 2a's "demonstrated capable of firing" requirement has no specified, legitimate mechanism reachable without either touching the forbidden scan file or inventing an unstated monkeypatch technique; the pin as designed targets a layer (B) that cannot structurally exhibit the failure it claims to guard against. |
| Acceptance criteria and validation quality | 20 | 17 | Nine items, most well-specified; item 2a specifically is not satisfiable as written per the defect above, which undermines exactly the acceptance item round 3 added to close a vacuous-test risk. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Unaffected — neither-control-set, boundary-admit, no-cost-on-refusal, latch-not-cleared all remain pinned and are not implicated by the pin defect, which is confined to the layer-B fallback's own self-check. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected — no cap value or magnitude read/assigned/implied; test-only, rollback risk nil. |
| **Total** | **100** | **88** | |

## Required changes (summary)

1. Either retarget the precondition pin at layer A's identifier-aware classification (the mechanism that can actually drift) or specify the exact, legitimate RED-phase inversion technique (e.g. a named monkeypatch pattern that never touches the scan module's own source, with `git diff` emptiness on that file stated as unaffected) that satisfies §8 item 2a's "demonstrated capable of firing" requirement.

## Blockers

None of the above requires an operator/strategy-lead ruling — this is a build-side test-design gap, fixable within the plan's own scope. R-12 remains open and out of scope as before, unaffected by this finding.
