# GAP-5 plan r3 — delta over r1 + r2 (ROI re-audit 2026-11-01: narrow to the census)

Applies on top of `plan_r1.md` + `plan_r2_delta.md`; where they differ this delta wins. Status: r3 — reviewer confirmation pending (architect + security).

## R3-1 Scope split: GAP-5a (now) and GAP-5b (conditional)
- **GAP-5a = step 0 + steps 1–3 only** (citation closure, read-only census over the 11-01 node log and durable store, signature classification H1–H5a/H5b). Cost ≈ 1 h, read-only, no code change, no pin change. Runs now, in parallel with the kill screens.
- **GAP-5b = steps 4–5 (X1–X3 exits, H5a backoff change, any pin re-computation)** is CONDITIONAL on BOTH: (i) the census CONFIRMS one signature at the r1 §5 threshold, AND (ii) a resting/maker family is still on the backlog with non-KILL edge evidence (GAP-6 S0 ≠ KILL or a GAP-3 passing cell). A book with no edge behind it earns nothing from faster binding.
- Step 2 (venue schema check) runs only if the census shows an H3 signature.

## R3-2 ROI mechanism stated
GAP-5a's value is diagnostic: it decides whether the live maker's 0 fills are a mechanics defect (fixable) or a regime fact (not). GAP-5b's value is realised only through a family that would otherwise be denied fills; it is never built ahead of that family.

## R3-3 Everything else in r1/r2 is unchanged (invariants, NO-SEND, pins in their own commit, L-12).

## R3-4 (security r3: required wording) durable-store hygiene for 5a
The durable store is opened read-only (SQLite `mode=ro`, or a copy in the session scratch). Raw bodies and raw journal lines stay in the scratchpad; `docs/evidence/gap5/` holds ordinals and counts only, with the r1 S-3 regex scan (ids, `Bearer`, key material, account numbers) passing before commit.

## R3-5 (architect r3: corrections to R3-1)
- The 5b scope line is REPLACED by: "GAP-5b = steps 4–6 (one fix per CONFIRMED H1–H4/H5a, the step-5 churn fix when its precondition holds, the step-6 pins/gate/merge). X1–X3 dominance, UNEXPLAINED and H5b mean build nothing: stop and report."
- The 5a source line is REPLACED by: "read-only census over the 10-31 and 11-01 trade-node journal (r1 §4-1/§5 denominator) and the durable store, read from a copy, with S-3 hygiene applied to both."
- Condition (ii) gains a third way to be met: "or GAP-4 live-small reaches its build stage" (r1 §2).
