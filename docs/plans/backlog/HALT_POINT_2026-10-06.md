# Development halt point: 2026-10-06 (~14:45Z)

At the operator's direction, all in-flight sub-agents have finished and development is paused here. This file is the single resume point. Read it first, then `docs/core/PROGRESS.md`. It supersedes `HALT_POINT_2026-10-04.md`.

## 1. Live state at halt (the bot keeps running; nothing below is paused)

| Item | State |
|---|---|
| Trade node | Normal 24 h cycle, 16:50Z → 16:40Z. Next launch is **16:50Z 10-06**. It loads the merged **F6 FQ entry veto**, which refuses every FQ entry until an F6b loss-stop producer exists. That is fail-closed and intended. |
| **FQ v1 halt** | **ARMED, automatic.** Transient user timers `breezy-fq-halt-20261006` (16:40Z) and `breezy-fq-halt-verify-20261006` (16:55Z) run `~/.local/share/breezy/ops/fq_halt_20261006.sh` and `fq_halt_verify_20261006.sh`. They are **lost on reboot**. The backstop supervisor drop-in `~/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` (orders off) stays in place. |
| **Check after 16:55Z 10-06** | Read `~/.local/share/breezy/ops/fq_halt_20261006.result` and `fq_halt_verify_20261006.result`. Expect `halted=True` and the boot line `permit not minted: orders not requested`. If either shows FAIL, the drop-in already keeps orders off. Re-check that `NeedDaemonReload=no` before any reload. |
| Collectors | `us-source-collector@{lamp,pfm,nbp}` timers are LIVE. F2 truth timers (`breezy-truth-fetch` 11:40Z, `-dataset` 12:40Z) are LIVE. The collector picks up the merged parser fixes (Pacific PFM dates, one-digit LAMP months) on its next timer run, with no restart needed. |
| Exec client | Byte-pinned sha `76784ce8…`, unchanged in every merge. |
| Operator caps | Untouched. Only the two budget caps are operator decisions. |

## 2. Merged and pushed this session (`feat/data-capture-and-risk`)

Every merge had a full gate with EXIT=0 before it was merged.

**F7b (offline e-process verdicts)**
- **Slice 1 ARCH-0-E25** `a8ca1c93`, `1ecacc87`: verdict keys, e-LOND, and a ceiling of 4.
- **Slice 2 core** `b6fe90b5`..`17aec28b`: e-process, KILL test, sealed `evidence_row`, `FqEvaluator`. It is dead in production by design: there is no forward-shadow source, and the guard is unpinned.

**F6 FQ-BRIDGE veto** `88dbda40`..`2c5f549a`. Includes the review fixes (deadman, latch, atomic cache, delivered-alert stale window, TOCTOU, parity freshness), plus the wall-clock test fix `7d31ed60`.

**F13**
- **B0 tooling** `700e85ee`, `37de71e5`.
- **Backfill fixes** `645574bc`, `0e1bcecf`, `31702b44`, `86e5c101`: oversize pages, 403 stops everything, instant cursor, Pacific PFM date fix.
- **LAMP archive backfill** `3e8ba25d`, `0d6cc711`.
- **LAMP one-digit-month header fix** `84c70d99`. This also protects the **live** parser from 2027-01-01.
- **Phase A blend** `4434ffb2`..`8fcc0561`: pure modules, frozen-prereg runner, veto descriptive, draft prereg.
- **PFM history fix** `0b2b4be5`, `c33d938d`: body-time placement, the 2021 LOT layout, MM cells, `--quarantine-dir`, strict body time.

**M1-v3 NO-longshot forward screen**
- Tool `a08c24d7`..`47d1b94c`. Test fix `e6f18c3e`.
- **PREREG FROZEN** `adb1cd8b`, stamped in `6fbc4f6b`.
- Window 2026-10-07..11-28. **Single read-once on or after 2026-12-07** (memory `m1v3-prereg-frozen-2026-10-06`).

**Docs**
- F13-R35 (LAMP remaining-hours feature).
- F13-R36 **B1 UNDERPOWERED**: MDE 3.25 °F vs a plausible effect of 0.5 °F. B1 and B2 are not run.
- M1-v3 plan READY.
- F7b plan READY (R1..R28).
- Open items: `FQ_LOSS_RESPONSE_2026-10-04/F6-F7b-F13B0-open-items_2026-10-06.md`.
- Evidence: `docs/evidence/f13/`.

## 3. State of data jobs at halt

| Job | State | Resume action |
|---|---|---|
| PFM backfill 08-25 → 10-06, all five WFOs | DONE, clean, with LOT, LOX and MTR re-run after the fixes. | None. |
| PFM backfill 2021-01-01 → 2026-08-24 (history) | PARTIAL. The 10-06 runs used pre-fix code: about 9.7k products were stored, then the stations stopped on `unplaceable_header`, and LOT 2021–22 refused everything as `table_header`. The 2023+ re-run was stopped at halt: it was still on the old code, OKX stopped on a minute-back rollover, and LOT and MFL hit `TransportTimeoutError` from IEM. The placement and layout fix is now merged (`c33d938d`). | Re-run the whole range once with the new code (idempotent): `BREEZY_LIVE=1 PYTHONPATH=src .venv/bin/python scripts/archive/us_source_backfill.py --apply --legs pfm --archive-root ~/.local/share/breezy/us_source_archive --start-date 2021-01-01 --end-date 2026-08-24 --request-budget 8000 --max-runtime-s 17000 --quarantine-dir <scratch>/pfm_quarantine --report-json <out>`, under `systemd-run --user -p MemoryMax=4G`, started after 17:10Z. It pauses itself before 16:30Z, so repeat until every leg is `complete`. **Open:** an IEM `TransportTimeoutError` currently ends a station as `error`. Add a bounded retry with backoff (LOW-MED) before the long run. |
| LAMP archive: monthly 2026-01..09 | The first run stored **nothing**: every block was dropped as `bad_header` because of the one-digit month. That is fixed in `84c70d99`. | Re-run `scripts/archive/lamp_archive_backfill.py --apply --legs mdl-monthly --request-budget 240`, then `--legs iem-lav --request-budget 50`, then `--legs mdl-yearly --request-budget 6` (≈3.8 GB tars streamed; start outside 16:30–17:10Z). |
| F13 B0 | DONE. Verdict F13-R36. | None. |

## 4. Next work, in priority order

1. **Phase A (forecast-blend edge, the main F13 route).**
   - Prerequisites: archives done (§3); C1 holding ≥14 days of measured lags (≈10-20); the A0 probe on which HH30 cycles publish `lavtxt_ext` (R35); a feature-assembly script that turns LAMP/PFM/MOS archives into the runner's JSONL (not built).
   - Then pin the prereg values. The draft proposals are in session scratch `phaseA/pin_proposals_r1.md`, copied into the open-items doc. Run the mandatory peer review (prediction-market-reviewer + architect).
   - Then freeze the prereg, and gate that freeze commit (memory `read-gate-exit-before-push`).
   - Only then score.
2. **F6b loss-stop producer.** Blocked on the F5 floor constant c and on F4 labels (AUT-6). The brief must carry 0755/0700 dirs, monotonic `as_of`, and the interface values (open-items doc).
3. **F5 pin request.** F7b calibration-guard thresholds plus the KILL constants. These need a prereg amendment and peer review.
4. **AUT-6 activation**, so AUT-2 labels can run.
5. Low: the census LAMP future-runs bug; the PFM backfill LOW items (sticky limit=1, duplicate truncated dates, month/DST continuation test).

## 5. Parked branches and worktrees

- `~/breezy-aut1-wp4` (`backlog/aut1-wp4-2026-10-04`): held for WP8 by plan. Unchanged.
- `.claude/worktrees/*`: old CF-12 and FQ worktrees from 09-29..10-01. Untouched.
