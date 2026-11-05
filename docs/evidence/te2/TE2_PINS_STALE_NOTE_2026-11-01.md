# TE2_PINS.json stale note (2026-11-01)

- `docs/evidence/te2/TE2_PINS.json:27` pins `src/breezy/analysis/nbp_calibration.py` at sha256 `5718264c...`.
- That module changed on 2026-11-01 (HOLDOUT-END plan r2): `Splits.holdout_end_exclusive` = 2026-10-02, new
  `"forward"` split label. New sha256 `eb5322a9...` (superseding commit: feat(holdout-end) 2f5df3a0; pins re-pinned in the following chore(pins) commit).
- Authority: `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` cl.1 and cl.4.
- TE-2 closed 2026-10-12. `TE2_PINS.json` and `docs/evidence/te2/phase_b/` are frozen artefacts (L-75) and are
  deliberately NOT edited.
- A Phase B provenance refusal (`fq_loss_taxonomy_provenance`) if the study were ever re-run is INTENDED:
  the pinned source no longer matches, which is the correct outcome for a closed study.
