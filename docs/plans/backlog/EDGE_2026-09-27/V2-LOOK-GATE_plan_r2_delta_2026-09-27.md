# V2-LOOK-GATE plan r2: delta over r1 (BINDING; this delta wins where it conflicts with r1)

## Round-1 review results (both reviewers ran blind)
- **architect:** REQUEST_CHANGES, with 3 blocking items. It verified every file:line claim and confirmed that the rulings do not grandfather v2.
- **domain:** ENDORSE-WITH-CHANGES, with 3 required changes.

Both reviewers agree: file the RA-9c2 hole as a SEPARATE item, and enforce its ordering relative to the RA-9f flip.

## V-1. Test construction: stay honest about what each test proves (architect B1, B2)
- **Real v2 UNDERPOWERED records.** At `test_hypothesis_ledger.py:561, :605, :627` and `test_hypothesis_triage.py:1153, :1208`:
  - Build real v2 UNDERPOWERED records with `register_hypothesis(..., mde_plausibility_bound=0.01)`, not with `_as_v2`.
  - This keeps `:568` testing real schema selection.
  - It also keeps the eager-filter-validation comment at triage `:1205-1207` true.
- **Where `_as_v2` is still used.** Only where a look-taking record is genuinely required: `:950` and the triage `_register` path that is given filters.

## V-2. Enforce the flip ordering in code (architect B3 + domain required change 1)
- **New constant.** `PATH_B_SOURCE_GATE_LANDED: Final[bool] = False` in `hypothesis_ledger.py`, next to `HORIZON_TOLLING_LANDED`. Its docstring cites RA-9 §7 Path B item 1 and A-7.
- **v3 refusal rule.** v3 look-taking stays refused unless BOTH flags are True. Add a new error class, `PathBSourceGateNotLandedError(ValueError)`, raised when `HORIZON_TOLLING_LANDED` is True and `PATH_B_SOURCE_GATE_LANDED` is False.
- **Error precedence.** The existing `HorizonTollingNotLandedError` stays the error when the tolling flag is False. The existing test at `:1103` is therefore unchanged.
- **New test T5, `test_v3_tolling_flip_alone_still_refuses`.** Monkeypatch `HORIZON_TOLLING_LANDED=True` and leave the source gate False. Expect `PathBSourceGateNotLandedError`.
- **Mutant M10.** Drop the second flag check. T5 must kill it.
- **Follow-up item.** File it as **PATH-B-SOURCE-GATE**; do not reuse the name of the STOPPED RA-9c2 item (RA-13 :34). Its scope: rule on the semantics (which `composition_kind` values need scoped sources), then build the gate and flip the flag.
  - In `PROGRESS.md` and in the comment at `hypothesis_ledger.py:146-150`, state that the RA-9f flip is inert until PATH-B-SOURCE-GATE lands.

## V-3. Name the residual in the module itself (domain required change 2)
Add a "Known residuals" paragraph to the `hypothesis_ledger.py` module docstring:
- Direct `HypothesisRecord` construction and hand-edited ledger lines bypass registration-time gates.
- `read_hypothesis_ledger` and triage only re-validate schema and filter shape.
- The only sanctioned writer is `register_and_persist`.

## V-4. Test changes (architect section 6, domain section 4)
- **T1:**
  - Pin `k_variants=1`, so it kills the new mutant M9 ("refuse only when k>1").
  - Assert that the error message cites `RA-9` and `Path B` (domain optional change 3).
- **T4:** DROP it. It duplicates `:1103`. Do not replace it with a flag-True v3 REGISTERED test, because that would pin the RA-9c2 hole as expected behaviour.
- **Honest scope statement.** Today the gap is LATENT: any MECHANISM_ONLY row trips C_VALIDITY first (`hypothesis_triage.py:674-677`). The gate is defence in depth.

**Confidence after r2:** HIGH. Every blocking item has a precise, reviewer-specified fix.
