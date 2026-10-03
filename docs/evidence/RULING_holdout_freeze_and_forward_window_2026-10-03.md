### C4.1 — `RULING_holdout_freeze_and_forward_window_2026-10-03` (ARCH-owned text; P3-1, P4-1)

Filed verbatim under `docs/evidence/` in Wave 0 after peer review (not an operator decision). AUT-3 and AUT-4 cite it by
name and never restate a variant.
1. **Freeze.** The NBP archive holdout is frozen at **[2026-07-01, 2026-10-02)**. `DEFAULT_SPLITS` (G37) gains
   `holdout_end_exclusive = 2026-10-02` by a reviewed L-12 widening (AUT-3), with a RED test that no fitter or screener
   reads a row inside it. It stays sealed for **one** final confirmatory use under the existing single-look marker
   (`nbp_calibration.py:330-345`).
2. **Forward data.** Days on or after 2026-10-02 are forward data. AUT-3 trains only on days before each candidate's
   `forward_eval_start_utc` (`train_end_lt_forward_eval_start`). AUT-4 evaluates on a rolling forward holdout of
   post-training days under the C4 α-spend.
3. **Contamination disclosure.** The September tape studies (WP-7b, AUD-02, the 09-20 terminal finding) touched
   [2026-07-01, 2026-10-01). S2 on that window is descriptive evidence only, never a confirmatory input.
4. A conflicting split in any AUT plan is void; changing this text is an ARCH change, re-reviewed.
