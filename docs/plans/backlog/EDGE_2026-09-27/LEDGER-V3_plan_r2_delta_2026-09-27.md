# LEDGER-V3 plan r2 — DELTA over r1 (BINDING; overrides r1 where they conflict)

Round-1 peers (all blind):
- architect: REQUEST_CHANGES (2 HIGH, 2 MED, 2 LOW)
- python-reviewer: MEDIUM (C 8 / I 9 / T 6 / R 8 / S 9 / F 8; 2 blocking)
- prediction-market-reviewer: REQUEST_CHANGES (6 edits)

Every item is resolved below.

## D-1 Drop `programme_alpha` (architect HIGH; domain edit 6)
- The field is forgeable: `replace(rec, re_arm_gating=True, programme_alpha=0.025)` passes on a record registered at 0.05. It is also redundant for any record that can gate.
- v3 adds exactly TWO keys: `horizon_days` and `re_arm_gating`.
- Invariant in `__post_init__`: `re_arm_gating is True and not is_zero_look ⇒ allocated_alpha * MAX_HYPOTHESES <= RE_ARM_GATING_PROGRAMME_ALPHA` (0.025).
  - Use **exact** comparison, with no tolerance, following the sibling check at `hypothesis_ledger.py:745` (python-reviewer).
  - Reading of A-3: "≤ 0.025", which is conservative. Say this in a code comment.
- `register_hypothesis` refuses `re_arm_gating=True` unless `programme_alpha_override` is given and is `<= 0.025`, for every outcome, zero-look included, so A-3 holds at registration time.
- **MAX_HYPOTHESES coupling (domain 5):** add a lock test asserting `MAX_HYPOTHESES == 4` and `RE_ARM_GATING_PROGRAMME_ALPHA == 0.025`. Its message states that the A-3 bound must be re-derived by a ruling before either value changes.

## D-2 Tolling guard enforced in code (architect HIGH; domain edit 1)
- Add `HORIZON_TOLLING_LANDED: Final[bool] = False` in hypothesis_ledger.py.
- While it is False, `register_hypothesis` refuses (ValueError) any v3 call whose result would be look-taking (status REGISTERED). v3 zero-look and CLOSED records remain allowed.
- RED test for the refusal. RA-9f flips the constant inside its own RED→GREEN and deletes this refusal test there (one reviewed change, L-12).
- The triage tests build `HypothesisRecord` directly, so they are unaffected.

## D-3 `horizon_days` comes only from ruled values (architect MED; domain edit 3)
- Add `RULED_HORIZON_DAYS: Final[frozenset[int]] = frozenset({120, 180})`, citing RULING_H-NO-SIDE (120) and RULING_H-ARCHIVE-RECAL / RULING_RA-9 (180) in a comment.
- `horizon_days` must be None (use the CLI value) or a member of that set. Anything else raises ValueError, including bools, <1 and 181.
- A new value needs a ruling that adds one row to the set (L-12). This rules out any forking path where the horizon is picked after seeing data.

## D-4 Registration fields are immutable after REGISTERED (domain edit 4)
- Triage calls `dataclasses.replace` at `hypothesis_triage.py:640/678/728/780`.
- Add `replace_record_status(record, **changes)` in hypothesis_ledger.py. It refuses (ValueError) any change to the registration-frozen fields: `horizon_days`, `re_arm_gating`, `k_variants`, `allocated_alpha`, `per_variant_alpha`, `variant_stratum_filters`, `registered_at`, `hypothesis_id`, plus the MDE and bound fields.
- Triage switches all four sites to it.
- Add an AST barrier test: no `dataclasses.replace(` / `replace(` of a HypothesisRecord appears in scripts/analysis/hypothesis_triage.py outside this helper.

## D-5 `may_gate_re_arm` has an enforced consumer (architect MED; domain edit 2)
- `may_gate_re_arm(record)` returns True only when ALL of these hold: `schema_version == 3`, `re_arm_gating is True`, `not is_zero_look`, and the D-1 α check. v1, v2 and UNDECLARED records return False.
- `_write_handoff` (`hypothesis_triage.py:441-452`, the only downstream artefact for a CONFIRMED record) adds the key `"may_gate_re_arm": may_gate_re_arm(record)`.
- Test: a research-only 0.05 CONFIRMED record produces `false`, and a gating 0.025 one produces `true`.
- Add an AST barrier test: no module other than hypothesis_ledger.py reads the attribute `.re_arm_gating`. Consumers must call the predicate.

## D-6 Schema-version selection rule (python blocking 1)
Pick the version as follows: V3 if either `horizon_days` or `re_arm_gating` is not None; otherwise V2 if `variant_stratum_filters` is not None; otherwise V1.
- v3 = v2 + 2 keys, so `variant_stratum_filters` is carried and v2's look-taking rule applies.
- A look-taking v3 call without `variant_stratum_filters` is refused explicitly in `register_hypothesis` (architect LOW), with a test.
- `horizon_days` without `re_arm_gating` is refused, as in r1 AC6.

## D-7 Test list completes the acceptance criteria (python blocking 2; architect LOW)
Add to r1's list:
- `test_v3_from_dict_refuses_missing_key`
- `..._refuses_extra_key`
- `..._refuses_null_re_arm_gating`
- `..._refuses_bool_horizon_days`
- `test_horizon_days_not_in_ruled_set_is_refused` (0, 1, 181, 90)
- `test_re_arm_gating_boundary_exact_0_025_passes_and_0_025_plus_eps_fails`
- `test_replace_record_status_refuses_frozen_field_change`
- `test_v3_look_taking_refused_while_tolling_not_landed`
- `test_v3_look_taking_without_filters_refused`
- `test_handoff_carries_may_gate_re_arm`
- the two AST barrier tests
- the MAX_HYPOTHESES lock test

Changes to existing tests:
- The renamed test `..._accepts_v1_v2_v3_and_refuses_v4` keeps its exact refusal assertions and ALSO asserts `_SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2, 3})` (exact equality).
- The version-99 test at `:132` is untouched.

## Unchanged from r1
- Option B: UNDECLARED legacy records fail closed.
- RA-9f is split out.
- `hypothesis_register.py` has no changes.
- `EVALUATION_SCHEMA_VERSION` is untouched.
- The live v1 ledger reads and round-trips byte-identically.
- No operator cap is touched, and there is no Nautilus change.
