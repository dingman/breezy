# AUD-17 round-5 delta review — trading-bot-architect

Plan: AUD-17-operator-caps-proven-through-the-v4-live-composition.md
SHA256: df21c342c630afa55a9b5fafdcd5aa5f9b48a5e0d33b56b8cf13bd7957bd4e9c
Round: 5 (delta on Revision 5, FINAL)
Reviewer: trading-bot-architect

## Scope of this round

Coordinator-scoped delta: verify the fix for silent-failure-hunter's round-4 MATERIAL defect (the
precondition pin at §7 17a step 2a was targeted at layer B — a byte-level census over env-var NAME
strings — which structurally can never see a bare identifier reference and therefore can never
fail, making "demonstrated capable of firing" unsatisfiable without either touching the forbidden
scan file or an unnamed monkeypatch technique), and reconcile my own round-4 deductions that named
no concrete defect+required-change.

## Verification performed this session

- `sha256sum` matches the coordinator-supplied hash exactly.
- Independently re-derived the scan module's two-layer structure from source, **before** re-reading
  the plan's account of it:
  - `files_naming_a_control()` (`test_operator_control_assignment_scan.py:347-358`) is confirmed a
    literal byte census against `CONTROL_ENV_VAR_NAMES` (the env-var NAME strings) — this is layer
    B, and it is exactly as blind to a bare Python identifier as the hunter's defect states.
  - `_mentions_control` (`:157-167`) is layer A: it walks the AST and returns `True` for either a
    literal matching `CONTROL_ENV_VAR_NAMES` **or** an `ast.Name`/`ast.Attribute` matching
    `CONTROL_CONSTANT_IDENTIFIERS` — i.e. layer A, unlike layer B, *can* see a bare identifier
    reference.
  - `PERMITTED_CONTROL_ARGUMENT_CALLEES` confirmed at `:126-136`; `_READER_CHAIN_CALLEES` at
    `:138`; the A6 rule confirmed at `:285-295` — "a control's NAME handed to an unapproved
    callable," firing when `callee not in PERMITTED_CONTROL_ARGUMENT_CALLEES | _READER_CHAIN_CALLEES`.
  - `find_control_assignments(path, source)` confirmed at `:224` — a public function taking a
    **source string**, not requiring a file on disk.
  - `SCAN_ROOTS = ("src", "scripts", "tests")` confirmed at `:86` — a new file under `tests/unit/`
    is inside the scan's root set and, per `:321`'s `exempt = whitelist | {DEFINITION_MODULE,
    SCAN_MODULE}`, is not exempt from layer A.
  - `test_the_scan_fires_on_every_planted_assignment_form` (`:452`) and
    `test_the_scan_does_not_fire_on_asserting_about_a_control_name` (`:470`) confirmed present —
    these are the existing repo precedent for feeding planted source strings to
    `find_control_assignments` for exactly this purpose, which the plan cites as its own idiom
    rather than inventing a new technique.
  Every citation the fix relies on is correct, and the defect the hunter named is real: layer B's
  byte census over `CONTROL_ENV_VAR_NAMES` cannot, by construction, ever flag a file that only
  references the identifier `MAX_POSITION_COST_USD_ENV_VAR` — the two string sets are disjoint by
  design, and that is precisely why the whole injection-seam design is safe in the first place.
- Read the retargeted §6/§7/§9 text (`:214-221`, `:282-347`, `:399-401`, `:449-478`) and confirm the
  fix does what it claims: the pin now asserts against layer A via `find_control_assignments`
  fed two **synthetic source strings**, never touching a real file or the scan module — branch (a)
  (the clean non-call shape) must return `[]`; branch (b) (the same identifier handed to an
  unapproved callee) must return a non-empty list carrying rule `A6`. Branch (b) **is** the firing
  demonstration, produced live in the same test run, so "capable of firing" no longer requires
  editing the forbidden file or inventing an unnamed monkeypatch — precisely the two dead ends the
  hunter identified as the only routes under the old (layer-B) design.
- Checked the corollary the hunter's defect implied but did not require: does retargeting to layer
  A also correct the §7 step 2 fallback logic itself (since "layer B's tolerance" was never the
  real constraint)? Confirmed yes — §7 step 2 (`:206-347` region) now runs **both** layers against
  a scratch draft, with a three-rung response ladder (rewrite into the non-call shape first; drop
  reason-equality only if no in-scope clean shape exists; never touch the scan under any branch) —
  correctly generalising the fix rather than patching only the narrow case the hunter tested.

I find the fix technically sound, complete against the defect as stated, and internally consistent
with the rest of the plan's existing constraints (§5's ban on touching the assignment scan, and the
`git diff`-emptiness acceptance items). No new defect introduced.

## Reconciliation of round-4 deductions (coordinator-requested)

Round 4 scored 97/100. Re-checking each deduction against the rule — every withheld point needs a
named defect AND a required change; real implementation cost or a correctly-scoped design choice
is a note, not a deduction:

- **Implementation specificity (14→15).** My round-4 reason was explicit and self-contradicting
  under the rule: "the two-permit-fixture construction and the exact synthetic-order shape remain
  the implementer's to build — **a real cost, not a design gap**." I had already concluded this
  was not a defect. Reconciled.
- **Acceptance (19→20).** My round-4 reason: "on the no-fallback path acceptance is a recorded
  answer rather than an artefact, which is correct but asymmetric with the fallback path's stronger
  evidence bar." This describes a deliberate, reasoned asymmetry (the fallback path carries the
  durability risk the precondition pin exists to guard; the no-fallback path carries none), not an
  unaddressed gap, and named no required change. Reconciled.
- **Autonomous operation (14→15).** My round-4 reason: "this item detects a broken cap only at
  test time, never at run time... the ceiling this criterion can reach for a test-only plan is
  inherently below what a runtime control item could earn." This imposes a ceiling based on the
  item's *type* (verification-only) rather than a defect *in* this plan — AUD-17 is correctly
  scoped as verification-only per its own stated class (§2: "a verification gap," not an
  enforcement gap), and adding runtime recovery behaviour would be out of scope, not a fix.
  Reconciled — the criterion is met as far as it correctly applies to a verification-only item.
- **Fidelity, technical correctness, portfolio (20/20/10, unchanged).** No deductions were made
  here in round 4.

## Defects

None remaining, MATERIAL or MINOR. The round-4 MATERIAL defect (the precondition pin's
structurally unfireable target) is verified fixed by retargeting to the correct, genuinely
drift-capable layer, using a legitimate mechanism (synthetic sources against the scan's own public
helper) the plan names explicitly rather than leaving to an implementer's invention.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | G-16 closed as stated, with the third denial cause folded in; still correctly scoped as verification-only. |
| Technical correctness and evidence grounding | 20 | 20 | The three-cause exception table (unchanged from round 4, re-confirmed by two prior independent reviewers) and the retargeted precondition pin's layer-A mechanics (`_mentions_control`, `PERMITTED_CONTROL_ARGUMENT_CALLEES`, `_READER_CHAIN_CALLEES`, A6, `find_control_assignments`, `SCAN_ROOTS`) all re-derived from source this session and correct. |
| Implementation specificity and feasibility | 15 | 15 | Ten named tests plus the retargeted pin, each in dependency order; the pin's firing mechanism is now literal (two synthetic source strings, one public helper call, no monkeypatch, no scan edit). |
| Acceptance criteria and validation quality | 20 | 20 | Nine items; ADMIT gates every denial; the differential is required in the transcript; the pin's two-branch output is now the specified "capable of firing" artefact rather than an unspecified demonstration. |
| Autonomous operation, failure handling and recovery | 15 | 15 | Neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared are pinned; the no-POST assertion runs under the no-egress sandbox; correctly adds no runtime control, matching this item's verification-only scope. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No cap value or magnitude read, assigned, or implied; R-12 and MP-B/R-11 routed to their owning rulings; test-only, rollback risk nil. |
| **Total** | **100** | **100** | |

## Required changes

None.

## Blockers

None. R-12 (session order-count ceiling) is open but explicitly out of scope and is not pre-empted
by this item. No operator-reserved value is read, assigned, or implied.
