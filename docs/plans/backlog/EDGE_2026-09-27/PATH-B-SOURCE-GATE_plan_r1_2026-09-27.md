# PATH-B-SOURCE-GATE plan r1 (2026-09-27, planner)

**PATH-B-SOURCE-GATE plan: recommendation is PARK (confidence about 80%)**

**Recommendation: PARK. Keep `PATH_B_SOURCE_GATE_LANDED=False` and settle the semantics now, on paper only.**
- The flag already fails closed. A v3 REGISTERED call raises `PathBSourceGateNotLandedError` (`src/breezy/analysis/hypothesis_ledger.py:1180-1186`). Before that check runs, `HorizonTollingNotLandedError` fires anyway, because `HORIZON_TOLLING_LANDED` stays False (`:164`, `:1174-1179`).
- The gate would have nothing to guard:
  - Nothing is registered with a look (`RULING_RA-13:47`).
  - Trigger-4 is killed at k=1 (`RA-13:17`). RA-9b and RA-10 are closed and RA-9c2 is stopped (`RA-13:34`).
  - H-ARCHIVE-RECAL is `UNDERPOWERED_NOT_REGISTERED` (`RULING_RA-9:226`).
  - RA-13 stops "any candidate-replay unit" (`RA-13:35`).
- There is no candidate source to scope against. Today every source is the champion, with one label and one path (`scripts/analysis/hypothesis_triage.py:173-174`). The scored-trial store path has no composition or family segment (`:177-186`), and the queue key has no composition dimension (`src/breezy/analysis/replay_results.py:62-64,323-328`). Designing the scoping now means guessing the layout of a candidate store that RA-9b was supposed to define (`RA-9:175-178`). That is speculative (YAGNI).
- It does not stop the goal state being reached. A future look can only come from R2, R3 or R4 (`RA-13:51-53`). Each of those is a new estimand that goes back through AUD-18 intake and must re-plan its own candidate source anyway (`RA-9:175`). The 2027-01-25 date is a governance backstop, not a clock on this item (`RA-13:95-97`). So parking takes nothing away from the path to a look.
- The flag is only half of Path B. A real gate also needs:
  - the other filter axes (station, hour_lst, side), which nothing applies yet (`hypothesis_ledger.py:379-383`);
  - `climate_day > registered_at` and the §3 trial filter (`RA-9:173-174`).
  "Scope by composition_kind, then flip the flag" would therefore be an under-built gate with a green flag on it. That is worse than False.
- The defence that exists today is enough. A hand-built record gets past registration (`hypothesis_ledger.py:26-32`), but triage still stops it at C_VALIDITY, because every row is `MECHANISM_ONLY` (`replay_results.py:58`; `hypothesis_triage.py:674-677`).
- **Reopen trigger (put in PROGRESS):** the first of these to happen:
  - R2, R3 or R4 fires (`RA-13:51-53`);
  - a ruling moves toward flipping `HORIZON_TOLLING_LANDED` (RA-9f);
  - a plan is filed for any candidate replay unit.

**Semantics ruling for the peer loop to decide (Q1)**
- **S-1. Exact match on a closed vocabulary.** Admit a row to a record's `completed` set and scored-trial store only when `row.composition_kind` equals the record filter's `composition_kind`. A row with a null `composition_kind` is never admitted (`replay_results.py:105,294`).
- **S-2. Vocabulary defect, to fix before building.** The filter's `composition_kind` is free text (`hypothesis_ledger.py:388,474`). Tests use `taker`, `test` and `pm_us_crh_offwindow_price_cap_v1` (`tests/unit/test_hypothesis_ledger.py:570,762`). Row values come from the manifest vocabulary: `current_rung_hold`, `continuous_rung_hold`, `forecast_ladder` (`tests/unit/test_replay_daily_runner.py:129,577-582`). The two vocabularies do not overlap, so an exact-match gate built today would admit nothing. That fails closed, but it is useless. The reopened item must first decide whether the join key is `composition_kind` or `family_id`. My recommendation is `family_id`, because a candidate is a family, and `family_id` is recorded on each row but deliberately left out of the queue key (`replay_results.py:324-327`).
- **S-3. A champion-row look is legitimate in exactly one case: the champion is the estimand.** That means the filter names the champion's own kind or family. Under S-1 this needs no special case.
  - A recalibration can never be scored on champion rows. H-ARCHIVE-RECAL tests a different, recalibrated design (`RULING_H-ARCHIVE-RECAL:47-48`), and champion rows reflect the frozen table.
  - Scoring the recalibration on champion rows is exactly what Path B item 1 forbids: "candidate rows and champion rows never merge" (`RA-9:172-173`). This holds for any R3 re-plan (`RA-13:52`) as well.
- **S-4. Decidable without the operator.** No operator cap is involved (`RA-13:69`), and venue and design questions belong to the peer loop (`RA-13:103`).

**Design sketch for when it reopens (not for now)**
1. **`scripts/analysis/hypothesis_triage.py`**
   - Change `_store_dir` (`:177`) to take the record's scope key and add it as a path segment, for example `.../v3/<scope>/<station>/...`.
   - Stop sharing one `completed` list across all records (`:825,838`). Filter it per record inside `_triage_record` (before `:674`), by S-1/S-2, `climate_day > registered_at`, and the other three axes.
   - Add the scope key to the duplicate check in `_load_replay_result_sources` (`:523-537`), so a candidate row and a champion row on the same day do not trip a false conflict.
2. **`src/breezy/analysis/hypothesis_ledger.py`**
   - Close the vocabulary (S-2), following the same pattern as `_STRATUM_SIDE_VALUES` at `:368`.
   - Flip `:172` in the same reviewed RED→GREEN change, and delete `test_v3_tolling_flip_alone_still_refuses` (`test_hypothesis_ledger.py:1194-1200`) there too, following the L-12 precedent (`hypothesis_ledger.py:159-161`).
3. **Tests (all RED first):**
   - champion rows are refused for a candidate-scoped record;
   - a null-kind row is refused;
   - `climate_day == registered_at` is refused;
   - two records each score only their own rows;
   - a candidate row and a champion row with the same key do not conflict;
   - the store path contains the scope.
4. **Mutants the tests must kill:** drop the per-record filter; swap `==` for `in`/prefix matching; admit null; use `>=` on the date; leave the scope out of the path; flip the flag without the triage change.

**Firewall compliance (Q4)**
- This plan came from reading code and rulings only. No tape, replay row or ledger line was opened, and no statistic was computed. No H-ARCHIVE-RECAL day is spent (`docs/plans/backlog/EDGE_2026-09-27/README.md:18`; `RA-13:90`).
- The future design only filters rows that triage already reads. It adds no new statistic, and its tests use synthetic fixtures only.

**Risk register**
- **R1: parking hides the gap.** The flag and its docstring already name the gap (`hypothesis_ledger.py:165-171`). Add the reopen trigger to PROGRESS.
- **R2: someone flips the flag early.** Refusing both vocabularies (S-2) turns any premature flip into a gate that admits nothing, which is safe. Require the flip to be reviewed together with the triage filter (the flip-without-triage mutant covers this).
- **R3: the direct-construction bypass** (`hypothesis_ledger.py:26-32`). This residual is accepted. C_VALIDITY backs it up (`hypothesis_triage.py:674-677`) until the RA-3/AUD-12 flip, and that flip is also a reopen trigger.
- **R4: an S-2 decision taken now could fix a key before RA-9b exists.** Record S-1 to S-3 as principles only, and decide the join key when the item reopens.
- **Invariants:** `HORIZON_TOLLING_LANDED` stays False. No operator cap, enablement setting or Nautilus file is touched. No safety, contract or firewall test is weakened.
## Coordinator disposition (2026-09-27, after a domain review that ENDORSED the plan with changes)
**The item is PARKED.** `PATH_B_SOURCE_GATE_LANDED` stays False. Both of the reviewer's required changes are adopted:

1. **Reopen triggers.** The item reopens on the FIRST of these to occur:
   - (i) RA-13 R2, R3 or R4 fires;
   - (ii) any ruling moves toward flipping `HORIZON_TOLLING_LANDED` (RA-9f);
   - (iii) a plan is filed for any candidate-replay unit;
   - (iv) **the RA-3/AUD-12 flip (`AUD11_AND_AUD12_LANDED`).** The C_VALIDITY backstop against the direct-construction bypass expires at that point, so the flip is a tracked trigger in its own right.
2. **The S-2 join key needs a signed amendment.** RA-9 §7 Path B item 1 literally names `composition_kind` as the selector. Adopting `family_id` instead therefore supersedes the ruling's wording, and requires a signed RA-9 amendment (precedent: A-3a) before any build that uses the changed key. It is not a design pick for the reopen-time peer loop to make.
