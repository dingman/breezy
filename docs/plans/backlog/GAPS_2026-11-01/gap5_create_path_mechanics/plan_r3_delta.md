# GAP-5 plan r3 — delta over r1 + r2 (ROI re-audit 2026-11-01: narrow to the census)

Applies on top of `plan_r1.md` + `plan_r2_delta.md`; where they differ this delta wins. Status: r3 — reviewer confirmation pending (architect + security).

## R3-1 Scope split: GAP-5a (now) and GAP-5b (conditional)
- **GAP-5a = step 0 + steps 1–3 only** (citation closure, read-only census over the 11-01 node log and durable store, signature classification H1–H5a/H5b). Cost ≈ 1 h, read-only, no code change, no pin change. Runs now, in parallel with the kill screens.
- **GAP-5b = steps 4–5 (X1–X3 exits, H5a backoff change, any pin re-computation)** is CONDITIONAL on BOTH: (i) the census CONFIRMS one signature at the r1 §5 threshold, AND (ii) a resting/maker family is still on the backlog with non-KILL edge evidence (GAP-6 S0 ≠ KILL or a GAP-3 passing cell). A book with no edge behind it earns nothing from faster binding.
- Step 2 (venue schema check) runs only if the census shows an H3 signature.

## R3-2 ROI mechanism stated
GAP-5a's value is diagnostic: it decides whether the live maker's 0 fills are a mechanics defect (fixable) or a regime fact (not). GAP-5b's value is realised only through a family that would otherwise be denied fills; it is never built ahead of that family.

## R3-3 Everything else in r1/r2 is unchanged (invariants, NO-SEND, pins in their own commit, L-12).
