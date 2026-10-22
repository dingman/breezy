# RULING_MAKER-S2_verdict_final_pin_retired_<DATE>

Status: **DRAFT** (A0′ of ARM plan r3 R4). Becomes FINAL in ONE reviewed commit that lands immediately BEFORE the `arm/integration` merge into `feat/data-capture-and-risk`. Decision owner per the operator's standing pre-authorization; no operator cap involved.

## Facts to fill at finalization
- S2 evidence commit: <S2_SHA> (records the MAKER-S2 verdict <S2_VERDICT> for the sealed second-look block 2026-10-14..<END>).
- C7 closure pin file `tests/unit/data/maker_stage0_c7_closure_pins.json` at <OLD_PIN_SHA> (commit-1 pin of the verdict closure).
- Files in the closure that the ARM B-chain changes (from `git diff <S2_SHA>..arm/integration -- <closure paths>`): <LIST> (expected: polymarket_us/config.py, exec/client.py, exec/submit_chain.py, no_id_attribution.py, adapters/polymarket_us/factories.py, runtime/node_config.py, account_activity.py, …).

## Ruling
1. The MAKER-S2 verdict recorded at <S2_SHA> is **FINAL**. No S2 re-run, errata run, re-scoring or re-read of the sealed block is permitted after the B-chain merge; any later question about S2 is answered from the artefacts at <S2_SHA> only.
2. Because the verdict is final, the C7 byte pin's job (proving the verdict-closure bytes are the ones the verdict was computed with) is complete. It is **retired by re-baselining**: the JSON digests are recomputed for the post-merge bytes in ONE reviewed commit, and `test_verdict_closure_bytes_match_the_commit1_pin` stays green at every commit (re-baseline lands first, B-chain merge second).
3. The re-baseline changes digests only; it adds or removes no path from the closure set (the set-equality assertion is unchanged), and the commit message lists every path whose digest changed with old → new.
4. This ruling licenses nothing else: no strategy promotion, no enablement. Arming is governed by `RULING_MAKER_sharp_v1_live_small_2026-10-21`.

## Review
PMR (verdict finality / no-rerun clause) + python-reviewer (re-baseline mechanics) before FINAL.
