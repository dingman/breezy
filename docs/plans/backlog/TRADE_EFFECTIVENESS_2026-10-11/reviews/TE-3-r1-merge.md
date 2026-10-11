# TE-3 r1 review merge: coordinator rulings (binding on r2)

Scores: domain 84 RWC · python 71 RWC · architecture 82 RWC · codex 76 NOT-READY. All four reviewers uphold the INFEASIBLE conclusion. Each also objects to how it is framed or supported.

## Rulings
1. **Primary basis is the ledger intake (R4), applied mechanically** (arch G2).
   - Use the existing token `UNDERPOWERED_NOT_REGISTERED`, with the rationale "structurally infeasible on PM.us". Do not mint `INFEASIBLE_NOT_REGISTERED`.
   - Cite the H-NO-SIDE-2026-09 record, and drop the optional new registration (arch G9).
   - State the ledger n as n_raw 1485.16, which rounds up to 1486 (codex F2).
2. **Lane-E arithmetic is corroboration only, and must be honest** (domain S1/S3/S4, codex "strongest argument").
   - Withdraw the claim "structural, independent of the rate".
   - Put the n_min range over the band's real break-even, p0 = 0.07 to 0.14 (fee rounds to 0 at an ask of 0.06–0.07). Use the exact binomial, and say the normal approximation is the lower figure.
   - Compute the PM.us ceiling for the earliest plausible freeze, 10-12. That gives a 98-day window and a ceiling of 490. Keep 10-26 / 420 as a second case.
   - Quote the two MDE families separately: the Bernoulli MDE at n_avail, and the ledger MDE at the pinned 0.25 variance.
   - Reject δ = 0.08 on prior grounds only (adverse fair-odds prior, SEARCH-picked band). Do not invoke the 0.04 ledger bound inside Lane E (domain S2).
3. **Census correction** (codex F1).
   - Interior rungs: 8 over 4 days, so λ̂ = 2.0/day. Recompute the exact Poisson 95% interval and n_avail.
   - The open-lower `lt65` tail is excluded.
   - Fix the dates (domain S6).
   - Fix the band as executable [0.06, 0.12] (`config.py:234-235`), consistently throughout (domain S5).
4. **WP-1 is DROPPED (YAGNI)** (arch G3).
   - Its number cannot change the verdict, so the python-review findings F1–F10 lapse.
   - The ruling quotes the preliminary census with its exact provenance: files, a read-only count recipe as an appendix snippet, 8 interior plus 1 open, and 2 reaching `taken`.
   - The census reads only tape dated ≤ 2026-09-25, so it is B-3 clean. State that, and that no `replay_sufficiency` row is read (arch G1).
   - WP-4 (dormant) inherits a binding requirement: every input refuses climate days after 2026-09-25 (arch G1). It also inherits the LST→UTC multi-UTC-day tape and the standalone no-lookahead check on the LST day end (py F1/F2). These are recorded so the dormant design is not lost.
5. **Every re-open trigger names a next action** (arch G5). For example, list TE-3 as a desk-only candidate in the K-2a plan, under R3V:55-61, with no PM.us bound reused (B-2).
6. **Additions to the premises.**
   - Add the AUD-01a NO-side calibration gate (`decision.py:484-485`, `config.py:247`). It is closed by default and is a further reason NO-1 is dead (arch G6).
   - Add a sentence on same-day cross-station correlation, which strengthens the verdict (domain S7).
   - Add a note that a station-day can hold both an M1-v3 favourite and a TE-3 longshot, so the two samples must never be pooled (domain).
7. **Deliverables now.** WP-2 is the ruling `docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_<date>.md`. WP-3 is bookkeeping. WP-4 stays dormant. There is no new code. The ruling text goes in the plan as an appendix draft, so peers review the exact words.
