# TE-2 FQ v1 loss taxonomy (generated, post-hoc diagnostic)

Verdict: **MODEL_MISCALIBRATED_UNATTRIBUTED** sublabel=None qualifiers=[] reason=None

## Provenance

- script sha256 (HEAD blob): `1ee00a6ff305b2ca4853a3d67f8e02d9cc9aecf9f27caff921a0fdf342dc439d`
- pins.json sha256: `9a8e0fa6981844ce52fa88f899ed221835f22adf9bb9228f52d480e53431dd59`
- reflog snapshot sha256: `f359e070c2334a31252782fbf949643dfac84bba1c0992fda73b7ef9094e427d`
- predeclaration commit: `526bdd112b97600073d5f0b6d5a4fa7160eb40bc` (file sha256 `b26bd6a3d785a3cf46850495c41a3f16a65bdebcb7213a5067ee77c2dfa3ef04`)
- Phase A table sha256: `d513445bfbc16bf293a1562d123aee79623af7efc625d15fcfa18d1d6a25b8ae`

## Tests (cluster level)

- T-WIN: rejected (p = 0.003469, TESTABLE)
- T-LOC: NOT-TESTABLE (minimum attainable p exceeds alpha; not a null result)
- T-SPREAD: did not reject (p = 0.7731, TESTABLE)
- T-ART: NOT-TESTABLE (minimum attainable p exceeds alpha; not a null result)

## Classes (ranked by share of loss)

- TAIL: 7 fills, share of loss 0.437
- BAND_SELECTION: 11 fills, share of loss 0.282
- SIBLING_WON: 2 fills, share of loss 0.155
- BOUNDARY: 3 fills, share of loss 0.127

Flags: {'FLANK_CHEAP': 10, 'LOC_SOURCE': 16, 'LOC_ARTEFACT': 4, 'K1b': 5}

## Consumers

- MODEL_MISCALIBRATED_UNATTRIBUTED: F13 r-next / T3 input; next evidence is T1 (12-07).
- BAND_SELECTION: T2 take-rule input (minimum-ask filter, consistent with M1).
- BOUNDARY: T2 input only; T-EDGE is exploratory (within model-expected near-misses).
- SIBLING_WON: T2 take-rule input (rung stacking).
- TAIL: PROGRESS row 'F13 r-next / T2-T3 candidate input' (descriptive baseline).
- K1b: Closed, no action: incident already fixed (0fe98eb4 + orders-off drop-in).
- NOT_TESTABLE_OR_CONDITIONAL: Feeds the INCONCLUSIVE forward-evidence sizing (route 1).

Delivery: {'soft_target': '2026-10-20', 'slip': None}
TE-1 cross-check pending

## Caveats

- diagnostic, post-hoc: the audit and triage showed the headline direction before the freeze
- ask_proxy is the fill's cumulative cost per unit; the decision-time ask is unauditable
- P_d sums p-hat taken at different cycles and assumes marginal calibration
- T-LOC is INDICATIVE and conditional on take; it never alone yields MODEL_LIMITATION/FIXABLE
- T-SPREAD and T-LOC are conditional on take (adverse selection); spread vs location is not identified, so a tail rejection is never attributed to spread alone
- PIN=INFERRED: the node imports the working tree at boot; the deployed commit is inferred
- H0-K / H1-K use the ask break-even a + theta*a*(1-a) summed per station-day (cap 1), max over the cluster, same clamp
- K3 uses the METAR/ASOS tmpf max over the local-standard day, rounded; K4 needs a venue file
- the raw-median T-LOC companion is not run (no raw pmf is stored); raw error is descriptive

## Footer

diagnostic, post-hoc, n = 14 station-days in 7 clusters, non-confirmatory
This verdict is NOT permission to re-arm. Re-open routes are T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (new US source, F13), per RULING_FQ-v2-NO-TRADE_2026-10-08.
VARIANCE does not imply positive EV.
