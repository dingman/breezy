# Plan: hypothesis-ledger schema v3 (RA-9d per-record horizon + RA-8c re-arm-gating flag)

## Facts the plan rests on
- **Live ledger**, read-only: `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl`. The path comes from `scripts/analysis/hypothesis_register.py:209` and `hypothesis_triage.py:144-148`. It holds 3 lines, all `schema_version: 1`, all `is_zero_look: true` (lines 1-3). They are byte-identical to `tests/fixtures/hypothesis/hypothesis_ledger_v1_2026-09-27.jsonl:1-3`.
- **How v2 did it (d10272b)**:
  - It added a new constant, `HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2`, and an allow-set (`hypothesis_ledger.py:104-114`).
  - Each version has its own field-types table (`:553-584`). `from_dict` picks the table by version, then refuses missing or extra keys (`:463-485`).
  - `to_dict` writes the new key only for that version (`:458-459`). `__post_init__` checks which fields each version may carry (`:411-430`).
  - `register_hypothesis` produces v2 only when the caller passes the new kwarg (`:812-824`); otherwise it writes v1 exactly as before. `disposition="CLOSED"` refuses the kwarg (`:752-753`).
  - Tests: `test_hypothesis_ledger.py:544-609`.
- **Horizon**:
  - `_DEFAULT_HORIZON_DAYS = 21` (`hypothesis_triage.py:90`). `_horizon_reached` is at `:550-552` (the brief's :543 is out of date). It is called at `:647` and `:680`, and the alert text at `:841` prints `args.horizon_days`.
  - The wrapper passes no `--horizon-days` (`deploy/systemd/hypothesis-triage-run.sh:42`). This matches RULING_RA-9 A-6 (`:224`).
  - Ruled horizons: 180 days (RULING_RA-9 `:116`, RULING_H-ARCHIVE-RECAL `:56`) and 120 days (RULING_H-NO-SIDE `:59`).
- **Zero-look records never reach the horizon check.** They have no eligible variant (`hypothesis_ledger.py:644-645`), so triage returns at `hypothesis_triage.py:635-645`. None of the 3 live records is at risk today.
- **α**:
  - `register_hypothesis` accepts `programme_alpha_override` and checks `0 < α ≤ 0.05` (`hypothesis_ledger.py:733-749`).
  - The record stores only `allocated_alpha`. An UNDERPOWERED record writes `allocated_alpha=0.0` (`:892`). So after registration, no record can show which programme α it used.
  - `src/breezy/analysis` contains no re-arm concept at all (grep for `re_arm|rearm|0.025` returns nothing).
- **Tolling (A-5, RULING_RA-9 `:223`)**:
  - `AUD11_AND_AUD12_LANDED` is a bare `False` constant with no date attached (`replay_daily_runner.py:154`, used at `:1114`).
  - While it is False, every row fails C-validity (`hypothesis_triage.py:366-367`, `:660-663`). But the horizon check at `:647` runs before that, so it is not paused.

## Options for `re_arm_gating`
| Option | Trade-off |
|---|---|
| A. Default `True`, with the 0.025 check | Breaks about 40 existing registrations that use 0.05 (for example `test_hypothesis_ledger.py:149-152`, `:167-177`). Reading v1/v2 records as gating would give them an α claim they never met. It also silently labels research records as gating. **Rejected.** |
| B. v3 registration requires an explicit bool; v1/v2 read as `None` = UNDECLARED | Legacy callers and live lines keep their bytes. A new public predicate `may_gate_re_arm(record)` returns False for UNDECLARED, so an undeclared record can neither gate a re-arm nor be counted as research-only. **PICK.** |
| C. Every NORMAL registration must declare, now | Would change the output of `register_no_side_underpowered` / `register_archive_recal_underpowered` (`hypothesis_register.py:260-334`), which mirror the live v1 lines. **Deferred.** It can be tightened later once B is in place. |

**Sub-pick: add `programme_alpha: float` to v3 (required, non-null).** Without it, a gating UNDERPOWERED record (α stored as 0.0) cannot prove α ≤ 0.025. It also stops a later `dataclasses.replace(record, re_arm_gating=True)` from slipping past the check, because `__post_init__` runs on `replace`. Triage already calls `replace` at `hypothesis_triage.py:640,678,728,780`. This is flagged for the peer review, since it is the only field beyond what the brief asks for.

## Decision on tolling: a separate item, RA-9f (not part of v3)
- Tolling applies the same way to every record, so it needs no new schema field.
- It does need a dated source for the day the RA-3 flag flips, which does not exist today (`replay_daily_runner.py:154`). Adding it belongs to RA-3's own ruling.
- It should also record the stall as a separate named cause (RULING_RA-9 `:116`).
- Ordering guard: RA-9f must be merged before any REGISTERED look-taking v3 record exists (RULING_RA-9 §7 Path B `:168-184`). There is no deadline pressure today: every live record is zero-look.

## v3 schema
Adds three keys: `horizon_days` (int, or null meaning "use the CLI value"), `re_arm_gating` (bool, never null) and `programme_alpha` (float). It also keeps v2's `variant_stratum_filters`, with its rule for look-taking records (`:421-430`).

New constant: `RE_ARM_GATING_PROGRAMME_ALPHA: Final[float] = 0.025`.

## Acceptance criteria
1. The live v1 fixture reads and rewrites byte-identically (existing test `test_hypothesis_ledger.py:570-579`, unchanged). The mixed rewrite test at `:602` is extended to v1+v2+v3.
2. `read_hypothesis_ledger` accepts {1,2,3} and refuses 4. The test at `:544` becomes `..._refuses_v4`, and the unknown-version refusal assertion is kept. The 99 case at `:132` is untouched.
3. A v1/v2 `to_dict` never writes the v3 keys. A v3 `from_dict` refuses a missing key, an extra key, a null `re_arm_gating`/`programme_alpha`, or a bool given as `horizon_days`.
4. `re_arm_gating=True` with `programme_alpha > 0.025` (override missing or larger) is refused, both by `register_hypothesis` and by `__post_init__`, which also covers `from_dict` and `replace`.
5. `re_arm_gating=False` with α = 0.05 registers fine, and `may_gate_re_arm` returns False for it.
6. `horizon_days` without `re_arm_gating` is refused. v3 kwargs are refused for `disposition="CLOSED"`. `horizon_days < 1` is refused.
7. Triage uses `record.horizon_days` when it is set and falls back to the CLI value when it is None. The HORIZON_STALL alert text names the horizon actually applied.
8. No operator cap is read or assigned, and no Nautilus file is touched.

## Tests first (RED → GREEN, all in `tests/unit/`)
- Fixtures:
  - `tests/fixtures/hypothesis/hypothesis_ledger_v2_2026-09-27.jsonl` (one look-taking v2 line)
  - `tests/fixtures/hypothesis/hypothesis_ledger_v3_2026-09-27.jsonl` (one gating record with 180 days, one research record with `null` horizon)
  - Test: all three versions read, each round-trips byte-identically, and a mixed file rewrite leaves the v1/v2 lines unchanged.
- `test_hypothesis_ledger.py`:
  - `test_re_arm_gating_without_0_025_override_is_refused`
  - `test_re_arm_gating_with_override_0_025_registers_v3`
  - `test_research_only_may_keep_0_05_but_never_gates`
  - `test_undeclared_v1_v2_record_cannot_gate_re_arm`
  - `test_replace_to_gating_above_0_025_raises`
  - `test_v3_from_dict_refuses_null_re_arm_gating`
  - `test_horizon_days_without_re_arm_gating_is_refused`
  - `test_closed_disposition_refuses_v3_kwargs`
- `test_hypothesis_triage.py`:
  - `test_v3_180_day_horizon_does_not_stall_at_day_22`: registered `2026-08-01`, as-of `2026-09-01`, must produce no alert. This is the regression twin of the existing test at `:795`.
  - `test_v3_180_day_horizon_stalls_at_day_181`
  - `test_v3_null_horizon_falls_back_to_cli`
  - The existing v1 test at `:795` stays unchanged and green.
- Out of scope here: the tolling RED `test_horizon_pauses_while_aud12_gate_closed`, which goes with RA-9f.

## Files to change
1. `src/breezy/analysis/hypothesis_ledger.py`:
   - add the V3 constant and allow-set (`:104-114`)
   - add the three dataclass fields with default `None` (after `:403`)
   - `__post_init__` version and α invariants (`:405-430`)
   - `to_dict` for v3 (`:458`)
   - `from_dict` V3 table, plus a `_NULLABLE_FIELDS` set replacing `:497-499`
   - `_HYPOTHESIS_RECORD_FIELD_TYPES_V3` (after `:584`)
   - `register_hypothesis` kwargs and checks (`:698-699`, `:751-753`, `:812-824`, and the records built at `:886-938`)
   - `may_gate_re_arm`; update `__all__` (`:~96`)
2. `scripts/analysis/hypothesis_triage.py`:
   - an `_effective_horizon(record, cli_days)` helper
   - change `_horizon_reached` (`:550-552`) and its callers (`:647`, `:680`, `:824`), and the alert text at `:841`
   - `EVALUATION_SCHEMA_VERSION` (`:87`) is not touched
3. `scripts/analysis/hypothesis_register.py`: no change. The legacy callers stay on v1.
4. Tests and fixtures as listed above.
5. `docs/core/PROGRESS.md`: close RA-9d and RA-8c, and open RA-9f.

## Risks
| Risk | Mitigation |
|---|---|
| Replacing the "refuses v3" test at `:544` could look like weakening a contract test | The refusal of an unknown version stays, now for 4. Call it out in the commit and the review. |
| UNDECLARED legacy records later used to gate a re-arm | `may_gate_re_arm` fails closed. Any future re-arm consumer must call it. Name that in the docstring and in PROGRESS. |
| A very large `horizon_days` could silence HORIZON_STALL | Only ruled values should be passed. The peer loop decides whether to add an upper bound; this plan does not invent one. |
| Without RA-9f, a v3 record stalls at day 181 even while AUD-12 is still closed | RA-9f is a hard precondition before any REGISTERED v3 record (Path B). |
| The worktree tests the primary tree by mistake | Set `PYTHONPATH` to the worktree. Run `scripts/ci/run_tests_no_egress.sh` and `lint-imports` after each slice. |

## Confidence
**High (about 85%)** on the schema and dual-read design, because it mirrors d10272b field for field. **Medium** on the `programme_alpha` sub-pick and on the α float-tolerance detail (use exact `≤ 0.025` or the existing `MDE_MISMATCH_TOLERANCE`, `:156`). Both should go to the peer review: architect, python-reviewer and prediction-market-reviewer.
