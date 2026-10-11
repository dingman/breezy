**VERDICT: READY. SCORE: 91/100.** No BLOCKER or HIGH finding remains. I read only the plan and its reviews, no outcome data.

**Confirmed**
1. **T-SPREAD union bound.** q_c = min(1, Σq_f) is the Boole upper bound on P(A_c=1) under any dependence. Using it for an upper-tail test makes P(X ≥ x) larger, so the test is conservative. It is stated at line 156 and consistent in S0-I (line 171) and power/H1-S (line 177). It is also in the S0-H table (line 282) and test #17. It does not break testability: a cluster with q_c capped at 1 gives p = 1, which is harmless.
2. **T-LOC relabel.** The "indicative" wording appears in line 149 and rule 2. It also appears in rule 4 (excluded from the unconditionally-TESTABLE count), in the TAIL attribution, and in the changes table.
3. **Matching null vectors.** Line 171 pins T-LOC to the π^min/π^max rule and T-SPREAD to the union q_c. Uniform 0.5 is reference only.

**Findings**

| ID | Sev | Finding | Fix |
|---|---|---|---|
| D1 | MED | Line 155 still says "Per day: q_d = max over the day's fills". Line 156 says q_d becomes min(1, Σq_f). The two contradict. | Delete the max wording in line 155. |
| D2 | MED | Rules 3 and 4 do not say how an indicative T-LOC rejection is treated. In rule 3, "no secondary rejects" is ambiguous when only T-LOC rejects. Rule 2 does not qualify it, so it would fall through to INCONCLUSIVE silently. | State that T-LOC rejections are ignored for the rule 3 and rule 4 "no secondary rejects" clauses. Alternatively, route T-LOC-only rejection to MISCALIBRATED_UNATTRIBUTED with a note. |
| D3 | MED | The test list has gaps. #28 covers only that T-LOC never yields FIXABLE. No test pins T-LOC-alone failing to qualify MODEL_LIMITATION or SOURCE. No test pins that S0-I testability uses the matching null vectors (T-LOC max-of-two, T-SPREAD union q_c). | Extend #29 and #32, or add a test. |
| D4 | LOW | The header at line 3 says "Status: r3.1". | Update to r3.2. |