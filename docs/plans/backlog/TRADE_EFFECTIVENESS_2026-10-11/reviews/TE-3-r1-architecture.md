VERDICT: READY-WITH-CHANGES
SCORE: 82/100

The INFEASIBLE verdict stands. Its firm basis is the ledger arithmetic: at the structural ceiling of 420 station-days, the MDE is 0.0752, above the 0.04 bound, so intake returns `UNDERPOWERED_NOT_REGISTERED` whatever the rate. The Lane-E argument is the fragile one: at δ=0.05, the high case has 287 available against 290 required. One HIGH firewall gap needs closing before WP-1 is built.

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| G1 | HIGH | WP-1 computes κ from `replay_sufficiency` rows with `window_complete`, but nothing limits those rows to dates up to 2026-09-25. The nightly census holds rows after 09-25. Counting them is a "post-freeze count" under B-3 and spends H-ARCHIVE-RECAL CONFIRM days. STOP-3 only pins the tape `--until` flag. | RA-13:90; plan:74,98 | Refuse any climate day after 09-25 from every input, row by row (tape, `replay_sufficiency`, offer tape). Add `test_replay_sufficiency_rows_after_0925_refused`. |
| G2 | MED | Under governance, the deciding basis is R4 (ledger intake), and it is mechanical. The plan instead leads with Lane-E n_min (445 vs 420), which is a 6% margin that depends on δ. Separately, the new token `INFEASIBLE_NOT_REGISTERED` is not in the ledger's vocabulary. | ledger:1125; R3V:42-46; plan:116,172 | The ruling's primary basis should be ledger intake. Lane-E arithmetic becomes corroboration. Use `UNDERPOWERED_NOT_REGISTERED` with a "structurally infeasible on PM.us" rationale. |
| G3 | MED | WP-1 cannot change the verdict, by the plan's own admission (§8). It only firms a verdict date that is moot. That is a build of 10 RED tests for a number that drives no decision (YAGNI). | plan:204-205 | Either make WP-1 optional, with the ruling quoting the preliminary 2.25/day and its interval, or state the decision it gates. |
| G4 | MED | WP-1 re-derives LST offsets itself. The repo already provides `decision_window_ns`, which uses the same 12–17 LST window that `window_complete` measures. The plan also does not dispose of the existing `ladder_ev_afternoon_coverage_census.py`, a 12–17 LST Depth10 census. | replay_sufficiency.py:147-151,207-222; ladder_ev_afternoon_coverage_census.py:46-58 | Reuse `decision_window_ns`. Add one line saying why the ladder_ev census is not extended (it reads raw parquet, YES ask only, hard-coded offsets). |
| G5 | MED | Under "no bare stop", re-open triggers alone are passive. No trigger has a named next action. | RA-13:54 | Each trigger gets a next action. For example, list TE-3 as a desk-only candidate in K-2a (allowed under R3V:55-61, with no reuse of PM.us's bound). |
| G6 | LOW | The plan omits the NO-side calibration gate (AUD-01a). It is closed by default and refuses every NO candidate as `no_side_calibration_unsafe`, a further reason NO-1 is dead. | decision.py:484-485; config.py:247 | Add it to §1/§2. |
| G7 | LOW | WP-1 imports private helpers (`_index_directories`, `_levels`), which are not in `__all__`. | market_calibration_scan.py:65-94,231,362 | Add a pin test that each helper exists with its signature (the M1V3-R27 precedent), or use the public `parse_slug`/`no_ask`. |
| G8 | LOW | No focused gate is listed. | brief duty 5 | Name the import/firewall/contract guards in WP-1's focused run, alongside `run_tests_no_egress.sh`. |
| G9 | LOW | The optional `_UNDERPOWERED_REGISTRATIONS` entry would be redundant: the `no_side_hunting` class is already recorded by H-NO-SIDE-2026-09. | hypothesis_register.py:151-174,479-496 | Drop it. The ruling cites H-NO-SIDE's record. |

**Judgements**
- **Goal state met by an INFEASIBLE ruling with no shadow path:** acceptable. It follows the H-NO-SIDE precedent. A forward collector would itself spend CONFIRM days under B-3, and a Lane-E WINNER is not a revival route under R3V. This depends on G5 being fixed.
- **WP-1 placement under `docs/evidence/te3/`:** acceptable. There is precedent in `docs/evidence/m1v3/*.py`, loaded by importlib in tests (`test_exec_parallel_dhat.py:25-39`). It is a one-shot input to a ruling, not a reusable tool, which is the case for `scripts/analysis`. Mirror the importlib test pattern.
- **Duplication:** none of `market_calibration_scan` (WP-1 reuses it, and its docstring at :25 says local-time variants are a new scan) or `hypothesis_register` (WP-2 entry is optional). Partial overlap with replay_sufficiency and the ladder_ev census (G4).
- **NO-SEND firewall and binding rules:** no violation. No package touches arming, halts, operator caps, PREREG, Nautilus or `allow_short`. The B-3 corpus firewall is the one gap (G1).

**Premises checked**
- P1, RA-13 §3 backstop 2027-01-25, firm, not extended by capture holes: CONFIRMED (:45-46, :97).
- P2, B-3 (any post-freeze count spends CONFIRM days): CONFIRMED (:90).
- P3, B-2 (no PM.us n/bound/α reused for Kalshi): CONFIRMED (:86-88).
- P4, B-5 (backstop is a firm calendar date for R2–R4): CONFIRMED (:94-97).
- P5, H-NO-SIDE §3 bound 0.04 and §4 n≈1487: CONFIRMED. The plan's 1485 is the same figure, rounded.
- P6, R3V §3.2 routes are R4 and T1–T3: CONFIRMED (:42-48).
- P7, v3a NO rule (`1−P_HOLD_UPPER`, current rung only): CONFIRMED (amendment :28, :36, :14).
- P8, ledger constants (`PROGRAMME_ALPHA`, `MAX_HYPOTHESES`, `POWER`, `VARIANCE_BOUND`, `recompute_mde`, intake check): CONFIRMED (:177, :181, :192, :196, :859-870, :1125).
- P9, `continuous_no_side.py:106` and the offer-tape append at :213-296: CONFIRMED.
- P10, `decision.py:383-392`, :455-496, :487-488 and `config.py:234-235`: CONFIRMED. Incomplete: the gate at :484 is omitted (G6).
- P11, M1-v3 PREREG (threshold 0.90, `frozen_sha` adb1cd8b, read offset 61 days) and plan :10/:91/:195: CONFIRMED.
- P12, arithmetic (445, 290, MDE 0.075 at 420, ceiling 420): CONFIRMED by recomputation.
- P13, offer-tape census (9 rungs, 7 refused as `observation_ambiguous`): NOT CHECKED. The files are gzipped and I had no shell under the read-only brief.

No M1-v3 outcome data was read. `reviews/TE-3-r1-domain.md` exists and I left it unopened, as the blind protocol requires.