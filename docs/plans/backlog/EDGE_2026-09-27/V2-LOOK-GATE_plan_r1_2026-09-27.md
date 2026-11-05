# V2-LOOK-GATE plan: refuse schema-v2 registrations that would take looks

## Findings (answers to Q1–Q3)
- **The gap is real.** `register_hypothesis` returns a v2 REGISTERED record with nothing stopping it (`hypothesis_ledger.py:1019-1020` → `:1130-1157`). The only refusal is for v3 (`:1117-1128`).
- **Triage would take the look.** A v2 record carries filters, so it passes `_has_registered_draw_binding` (`hypothesis_triage.py:594-619`) and reaches `assert_look_permitted` / the bootstrap (`:698-711`). Two things are wrong with the rows it would use:
  - They are champion-only. `_default_replay_result_sources` (`:173-174`) and `_store_dir` (`:177-186`) are not scoped by `composition_kind`. RA-9c2 is still unbuilt (RULING_RA-9 A-7 `:229`).
  - The horizon is the 21-day CLI value (`:556-560`; A-6 `:228`).
- **v1 look-taking records are already blocked.** They carry no filters, so triage stops them with MISSING_STRATUM_BINDING (`:664-672`). They are out of scope.
- **Nothing on disk is affected.**
  - The live ledger path is `derived_root/hypothesis/hypothesis_ledger.jsonl` (`hypothesis_triage.py:146-154`). I read the first lines only: 3 lines, all v1, all `is_zero_look:true`.
  - No production caller passes `variant_stratum_filters`. `hypothesis_register.py:248-333` only makes CLOSED/UNDERPOWERED records.
- **One fixture holds a v2 REGISTERED line:** `tests/fixtures/hypothesis/hypothesis_ledger_v2_2026-09-27.jsonl:1`. It is read by `test_hypothesis_ledger.py:1146,1163`, so the read path must stay unchanged.
- **Some existing tests build v2 REGISTERED records through `register_hypothesis`** and will break unless their setup changes:
  - `test_hypothesis_ledger.py:561, :605, :627, :950` (`_valid_kwargs` bound 0.5 gives REGISTERED, `:113`)
  - `test_hypothesis_triage.py` `_register` `:171-190`, used with filters at `:429/465/524/558`, plus `:1153` and `:1208`
- **The rulings do not grandfather v2.**
  - RULING_RA-9 §7 Path B (`:168-184`) bars *any* REGISTERED look-taking record until RA-9c2, RA-9b, RA-9d and RA-9e land.
  - RA-9d (a per-record horizon) can only be expressed in v3: `horizon_days` is rejected on v1/v2 (`hypothesis_ledger.py:516-522`).
  - A-3 (`:218-221`) needs a declared re-arm flag, and v2 cannot declare one (`may_gate_re_arm` returns False, `:1178`).
  - RA-13 `:47` assumes "nothing is registered with a look". The gate keeps that true.
  - So a v2 look-taking record can never meet Path B, and a permanent refusal is consistent with the rulings.
- **Naming mismatch.** PROGRESS `:63` calls this the "RA-9c hard gate", but LEDGER-V3 D-2 is the RA-9f tolling gate (`hypothesis_ledger.py:146-151`). I treat the item as "close the v2 hole in the Path B gate".

## Options
| Option | Verdict |
|---|---|
| A. Refuse v2 REGISTERED under the same `HORIZON_TOLLING_LANDED` flag | Rejected. Flipping the flag for RA-9f would re-admit v2 with the 21-day horizon and no re-arm declaration. |
| **B. Refuse v2 REGISTERED permanently, in the REGISTERED branch only** | **Pick.** One line of logic. All new look-taking work goes through v3, which D-2 governs. |
| C. Also refuse in `__post_init__` or at triage time | Rejected. It breaks the v2 fixture read (`:1146`) and every triage look-path test. D-2 has the same scope (registration only). |

## File-by-file
1. **`src/breezy/analysis/hypothesis_ledger.py`**
   - Add `class V2LookTakingRegistrationRefusedError(ValueError)` after `:318-322`, and add it to `__all__` (around `:64`).
   - In the R3-2 block, after the power check, add a v2 branch that raises before the v3 block at `:1117`. The message cites RA-9 Path B item 3 and A-3.
   - Update the docstring at `:877-886`: only a v2 outcome of UNDERPOWERED is now accepted.
2. **`tests/unit/test_hypothesis_ledger.py`**
   - Add a test-local `_as_v2(rec, filters)` = `dc_replace(rec, schema_version=2, variant_stratum_filters=filters)`. `__post_init__` re-validates it, and every alpha/MDE value is the one `register_hypothesis` computed.
   - Use it at `:561, :605, :627, :950`. Every existing assertion stays byte-identical.
3. **`tests/unit/test_hypothesis_triage.py`**: same change in `_register` (`:171-193`, when filters are given) and at `:1153` and `:1208`. No triage assertion changes.
4. **`scripts/analysis/hypothesis_triage.py`**: no change.
5. **`docs/core/PROGRESS.md:63`**: close V2-LOOK-GATE and open RA-9c2-GATE (see Risks).

## Tests
| Test | Why |
|---|---|
| T1 `test_v2_look_taking_registration_is_refused` | RED: today it returns a v2 REGISTERED record (`:1130`). Asserts the specific error class. |
| T2 `test_v2_underpowered_registration_still_writes_v2` (bound 0.01) | Guard, already GREEN: the record keeps its filters and schema 2. |
| T3 `test_v2_refusal_survives_tolling_flag_flip` (monkeypatch `HORIZON_TOLLING_LANDED=True`) | RED today. Kills mutant M6. |
| T4 `test_v3_look_taking_still_raises_tolling_error_not_v2_error` | Checks the existing `:1103` together with a v3+filters case. |
| Existing guards, unchanged | v2 fixture round-trip (`:1146`); the ~40 v1 REGISTERED tests; the v3 tolling test (`:1103`). |

## Mutants the tests must kill
| # | Mutant | Killed by |
|---|---|---|
| M1 | Delete the v2 branch | T1 |
| M2 | Test `== V3` instead of V2 | T1 |
| M3 | Move the refusal next to the filter check (`:1005-1015`) | T2 |
| M4 | Gate on "filters is not None", which also catches v3 | T4 |
| M5 | Put the refusal in `__post_init__` | fixture test `:1146`, triage suite |
| M6 | Condition on `not HORIZON_TOLLING_LANDED` | T3 |
| M7 | Use `!= V3`, which also refuses v1 | the existing v1 REGISTERED tests |
| M8 | Raise a bare `ValueError` | T1 |

## Risks
- **Test setup edits could look like weakening tests.** Mitigation: they are harness-only, every assertion stays the same, and the diff says so in the review.
- **The gate can be bypassed** by building a `HypothesisRecord` directly or hand-editing the ledger. That is the same residual D-2 has; the only production writer is `register_and_persist`.
- **Out of scope, but real: the v3 gate checks only RA-9f.** RA-9c2 (stratum-scoped sources, Path B item 1) has no code gate, so flipping `HORIZON_TOLLING_LANDED` alone would admit v3 records onto champion rows. This needs a follow-up item, RA-9c2-GATE, and goes to the peer loop.
- **Worktree hygiene:** set `PYTHONPATH` to the worktree, then run `run_tests_no_egress.sh` and `lint-imports`.

## Firewall and invariants
- No tape is read and no statistic is computed. The change is registration logic only, so no H-ARCHIVE-RECAL station-day is spent (README `:18`).
- No operator cap, no enablement change, `allow_short` untouched, no Nautilus file touched.
- The only safety test touched is new or stricter.

## Confidence
**High (about 85%)** on B and where it goes. **Medium** on the RA-9c2 finding, which needs the peer loop to say whether it belongs in this item or a new one.