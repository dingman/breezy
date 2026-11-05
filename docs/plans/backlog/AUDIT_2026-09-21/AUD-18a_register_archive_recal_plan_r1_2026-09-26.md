# AUD-18(a): register H-ARCHIVE-RECAL-2026-09 as UNDERPOWERED_NOT_REGISTERED (plan r1, 2026-09-26; UNDER PEER REVIEW)

Sources:
- Ruling: `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md`
- Plan amendment: `AUD-18-strategy-design-backtest-iterate-programme.md:1219-1266`
- Code: `scripts/analysis/hypothesis_register.py`
- Tests: `tests/unit/test_hypothesis_register.py`
- Library: `src/breezy/analysis/hypothesis_ledger.py:485-673` (unchanged)
- L-50: `LESSONS.md:1562`

## Acceptance criteria
- **AC1.** The `ARCHIVE_RECAL_*` constants exist, and each one equals the exact string in the ruling. A T1-style test pins each constant to the ruling text.
- **AC2.** `--register-underpowered H-ARCHIVE-RECAL-2026-09` writes one zero-look record with:
  - status `UNDERPOWERED_NOT_REGISTERED`
  - `allocated_alpha` = 0.0 and `per_variant_alpha` = 0.0
  - the programme budget unchanged
- **AC3.** Check-before-write uses `require_status="UNDERPOWERED_NOT_REGISTERED"`. If the design is powered up, the ledger bytes and mtime stay unchanged. A second run exits 1 and changes nothing.
- **AC4.** The forecast-taker and NO-side lines stay byte-identical.
- **AC5.** An unknown id exits 2 and writes no file.
- **AC6.** A `--registered-at` earlier than 2026-09-25 exits 2. The date gate is per hypothesis.
- **AC7.** The host ledger reads back as exactly {FORECAST-TAKER, H-NO-SIDE-2026-09, H-ARCHIVE-RECAL-2026-09}, with no look-taking record.
- **AC8.** The full gate, ruff, mypy and lint-imports all pass.

## Constants (ruling line = exact pinned text)
| Constant | Value | Ruling line |
|---|---|---|
| ID | `H-ARCHIVE-RECAL-2026-09` | :44 |
| CLASS | `pm_us_crh_v4_archive_recalibration` | :45 |
| K_VARIANTS | 1 | :48 ("0.0125 / 1 = 0.0125") |
| MIN_STATION_DAYS | 600 | :64 |
| PER_VARIANT_ALPHA | 0.0125 (= PROGRAMME_ALPHA / MAX_HYPOTHESES / K) | :59 |
| MDE | 0.0629 (recomputes to 0.06293; tolerance 1e-4) | :65 |
| PLAUSIBILITY_BOUND | 0.03 | :85 and :95 |
| REFERENCE_ASK | 0.30 | :73 |
| SLIPPAGE | 0.01 | :75 |
| Fee theta | `EVIDENCED_FEE_THETA` (0.0695) | :73 |
| FREEZE_COMMIT | `49261a5c2119fc621863ad7df05af1e2a96c6b55` | :55 |
| RULING_DATE | 2026-09-25 | — |
| Signature | CONFIRMED-WITH-NOTES; ":137 condition is closed" | :141 and :161 |

The 180-day KILL horizon (:54) is deliberately omitted because only registered looks use it.

## Files
**`scripts/analysis/hypothesis_register.py`**
- Add the constants, each with a comment giving its ruling line, and add them to `__all__`.
- Fix the "not registrable" comments at :130-135 and :27-30.
- Add `register_archive_recal_underpowered(*, path, registered_at)`, mirroring `register_no_side_underpowered` at :214-249. It reads module globals at call time.
- Change the choices at :277.
- In `main`, map each id to (fn, ruling date, ruling file) instead of the single `NO_SIDE_RULING_DATE` gate at :316-322.
- No generic spec abstraction (YAGNI).

**`tests/unit/test_hypothesis_register.py`**
- Add `ARCHIVE_RECAL_RULING_PATH`.
- Supersede T6. The refusal property is kept and retargeted to an unknown id.

**`deploy/systemd/README.md:1571-1575`**
- Add a third sequential registrar line.

**`PROGRESS.md`**
- Update after the host run.

## Tests
- **T1** `test_archive_recal_constants_match_ruling_lines`
- **T2** `test_register_underpowered_archive_recal_writes_zero_look_record`
- **T3** `test_archive_recal_powered_up_design_leaves_ledger_unchanged`: monkeypatch the bound to 0.20 and expect `UnexpectedRegistrationStatusError` with the bytes and mtime unchanged.
- **T4** `test_archive_recal_cli_second_run_exits_one_file_unchanged`
- **T5** `test_archive_recal_append_keeps_existing_lines_byte_identical`
- **`test_unknown_hypothesis_is_not_a_registrable_choice`**: a preservation guard, so it is green immediately.
- **`test_archive_recal_registered_at_before_ruling_date_refused`**
- **Removed** `test_archive_recal_is_not_a_registrable_choice`, citing ruling :161.

## Host run (sequential, L-50)
Before the run:
- Confirm `breezy-hypothesis-triage.service` is inactive, and never run inside [01:15Z, 01:45Z).
- Confirm no `hypothesis_(register|triage).py` process is running.
- Copy the ledger to the scratchpad.
- Check that the id is absent from the ledger.

Then run:

`systemd-run --user --wait --pipe --collect -p MemoryMax=512M --working-directory=/home/jon/breezy .venv/bin/python scripts/analysis/hypothesis_register.py --registered-at 2026-09-26 --register-underpowered H-ARCHIVE-RECAL-2026-09`

## Verification (L-30)
- The id set is exact.
- The new record's fields match the table.
- `programme_budget_remaining == 4`.
- The earlier lines are byte-identical to the pre-run copy.
- The next triage run reports "CLEAN no look-taking" together with the read-back.

## Risks
- **HIGH.** Lost update from the triage timer (L-50). Mitigated by the pre-run checks and the run window. A registrar lock is a backlog item.
- **MEDIUM.** The ruling header (:11) still says DRAFT, but the dated passes (:130, :139-161) and amendment :1246 close it. T1 pins :161.
- **MEDIUM.** The ruling is PROVISIONAL on the AUD-12 slippage value, so any re-issue gets a new id (-R2).
- **LOW.** MDE rounding.

Confidence ~90%.

## r1.1 (domain review: prediction-market-reviewer, REQUEST_CHANGES → addressed)
- **Citations corrected.** k_variants comes from the canonical row `| k_variants | **1** |` (originally :46), and min_station_days from the canonical row `| min_station_days ... | **600** |` (originally :50). T1 pins exact STRINGS, not line numbers.
- **Line numbers shifted by +2.** On 09-26 the coordinator added a STATUS line under the ruling header: "SIGNED 2026-09-25, superseded by the dated peer passes". It changes no value. Every ruling line number in this plan therefore moves down by 2.
- The reviewer confirmed:
  - zero-alpha UNDERPOWERED is the ruling's conclusion (§4, :99);
  - the other two records' bytes and the budget are unaffected;
  - omitting the KILL horizon is correct;
  - no values are untraceable.
