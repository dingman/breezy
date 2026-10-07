# Development halt point: 2026-10-07 (~22:20Z)

At the operator's direction, all sub-agents have finished and every session shell and one-off backfill job is stopped. This file is the single resume point. Read it first, then `docs/core/PROGRESS.md`. It supersedes `HALT_POINT_2026-10-06.md`.

The integration branch `feat/data-capture-and-risk` is pushed and clean at the commit that adds this file. The only other worktree is the parked `~/breezy-aut1-wp4`.

## 1. Live state at halt (keeps running; nothing below is paused)

| Item | State |
|---|---|
| Trade node | Normal 24 h cycle (16:50Z → 16:40Z). The FQ entry veto stays fail-closed: no F6b producer yet. The FQ v1 orders-off supervisor drop-in is still in place. |
| Collectors | `us-source-collector@{lamp,pfm,nbp}` plus the new **C1 lag legs `@{lav,mos,obs}`**. The lag legs were enabled 10-07 at about 08:10Z, and all three have recorded `seen` rows. Totals at halt: lav 80, mos 10, obs 72, lamp-live 84, pfm 53. The obs leg is report-minute-targeted, at most about 216 requests per station per day. Every leg backs off 30 min on a 429, a 5xx or a 403. |
| F2 truth timers | 11:40Z and 12:40Z. Both scheduled runs on 10-07 succeeded: every station committed ok, and `coverage_gap_days=1`. |
| Exec client / operator caps | Untouched. |

## 2. Merged and pushed on 10-07

Every merge had a full gate with EXIT=0, read separately, and was CODE-IDENTICAL to the tested sha.

- **Phase A feature builder**, plus both review rounds: `cefe0b6b`..`0931d625`.
- **FB-R15: `obs_so_far` comes from the routine-METAR store.** The 1-min archive disagrees with the METAR value on 17–22% of hours, while the mean of 5 one-minute values matches on 99.6% or more.
  - Probe, store and rederive: `f3fe2db8`..`4a1d9268`.
  - Store: `~/.local/share/breezy/us_source_archive/metar-routine/`, 5 stations × 2021–2026H1, re-derived with the live T-group parser.
- **Pins r3 and freeze protocol (PIN-R1..R10)**: `9a6ea833`. The guards are `f1260885` and `72c5085d`.
  - The skeleton `F13_prereg_blend_v1.json` holds every fixed value. Still null: `source_lags_ns` and `source_breaks`. `frozen_sha` is UNFROZEN.
- **C1 lag evidence and legs (C1-R1..R4)**: `5d1af630`, `317318ee`..`cfcd9ab8`. The producer is `scripts/analysis/c1_lag_evidence.py`.
- **5-station NBP store** `~/.local/share/breezy/derived/nbp5` (KNYC added): `6a06d48b` plus evidence `fba22bbd`.
  - It is a superset of the 4-station store, and identical to it except for `fetched_at_ns`.
  - 9 cycles are genuine S3 gaps.
- **Fixes:**
  - mos/lav 00Z bare-date runtime: `fc50ec03`.
  - Backfill retries a server disconnect: `66fe261d`.
  - LAMP yearly `--download-deadline-s`: `d2427129`.
  - Census caps LAMP runs at now: `e5d03801`.
  - PFM parser accepts the LOT CDT layout (23Z/18, 11Z/06) and gains `--reingest-quarantine`: `b805364f`.
  - nbp_backfill tests independent of the wall clock: `ac5573a8`.
- **Docs and evidence:** FB-R15, pins r3, C1 rulings, `docs/evidence/f13/metar_*`, `nbp5_backfill_*`.

## 3. Data jobs at halt

| Job | State | Resume action |
|---|---|---|
| LAMP MDL yearly 2021–2025 + monthly 2026 | **DONE**, all complete. 53–79 runs a year are genuinely missing at the source. | None. |
| NBP 5-station 2021-01..2026-06 | **DONE** (`derived/nbp5`). | Point the builder at it: `--nbp-root ~/.local/share/breezy/derived/nbp5`. |
| Routine-METAR store | **DONE**, re-derived. | None. |
| PFM history 2021→2026-08-24 | **PARTIAL.** LOX is complete. LOT was stored to 2024-01-25. MFL, OKX and MTR are partial. The run was stopped at halt. It had no report, which is expected on SIGTERM; the store is idempotent. | **(1) Re-ingest LOT** offline (8,834 products), from the durable copy: `PYTHONPATH=src .venv/bin/python scripts/archive/us_source_backfill.py --reingest-quarantine ~/.local/share/breezy/quarantine/pfm_2026-10-07 --reingest-reasons extrema_under_unexpected_hour --archive-root ~/.local/share/breezy/us_source_archive --apply --report-json <out>`. Try `--dry-run` first: the archive-root level (parent vs `us-pfm-afos`) is untested. **(2) Resume the history**, outside 16:30–17:10Z: `systemd-run --user -p MemoryMax=4G ... BREEZY_LIVE=1 .venv/bin/python scripts/archive/us_source_backfill.py --apply --legs pfm --archive-root ~/.local/share/breezy/us_source_archive --start-date 2021-01-01 --end-date 2026-08-24 --request-budget 9000 --max-runtime-s 38000 --quarantine-dir ~/.local/share/breezy/quarantine/pfm_<date> --report-json <out>`. Repeat until every WFO is `complete`. Run only one IEM job at a time. |
| GFS MOS archive incl. KNYC (FB-R12) | **NOT RUN.** It refused: `BREEZY_USER_AGENT must name a monitored contact`. | Run with the existing operator env: `systemd-run --user -p EnvironmentFile=%h/.config/breezy/breezy.env ... us_source_backfill.py --apply --legs gfs --start-date 2021-01-01 --end-date 2026-06-30 --request-budget 60 --gfs-request-budget 60`. That is about 25 requests. Run it after the PFM history, never at the same time. |

Run reports and logs from 10-07 are copied to `~/.local/share/breezy/quarantine/run-reports-2026-10-07/`. The session scratchpad is not durable.

## 4. Next work, in priority order

1. **Phase A freeze path** (main F13 route; protocol in `F13-phaseA-pin-proposals_r3.md` §D/§E).
   - (a) Finish the PFM history, the LOT re-ingest and the GFS MOS archive (§3).
   - (b) **C1-R4:** `_check_c1` must count and require by the five pin keys (`lamp-mdl, lav-iem, pfm, mos-gfs, obs`), not by `LEVEL_SOURCES`. The runner can never pass until then.
   - (c) A full-history `--draft-scratch` engineering smoke build with `--nbp-root …/nbp5`. It needs about 12 GiB `--max-memory-gib`, and must not run at the same time as another heavy job.
   - (d) Derive `source_breaks` from the archive and provenance reports only (PIN-R7).
   - (e) On or after **~2026-10-21**, once every C1 source has ≥14 measured days and ≥30 uncensored samples, run `c1_lag_evidence.py`. Then derive `source_lags_ns = max(floor, p99)`, make **one** gated freeze commit, stamp it, set `FROZEN_CONTENT_SHA256`, and push.
   - (f) Build the scored primary pair plus the lag twin, then run stages A–C.
2. **PFM follow-ups** (LOW, from the domain review):
   - Within a table, a repeated MAX date should raise `duplicate_day`.
   - Add a docstring note on the CDT-era 06–18 window.
   - Spot-check the LOT 2021–24 MAX against CLI highs before those years carry weight.
3. **F6b loss-stop producer.** Blocked on the F5 floor c and on F4 labels (AUT-6). The brief must carry the open-items interface values.
4. **F5 pin request** (F7b guard thresholds plus the KILL constants), via prereg amendment and peer review.
5. **AUT-6 activation.**
6. **M1-v3:** a single read on or after 2026-12-07. Never edit its PREREG.

## 5. Parked

- `~/breezy-aut1-wp4` (`backlog/aut1-wp4-2026-10-04`): held for WP8 by plan.
- `.claude/worktrees/*`: old CF-12 and FQ worktrees from 09-29..10-01, left untouched.
