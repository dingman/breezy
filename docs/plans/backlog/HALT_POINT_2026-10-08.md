# Development halt point: 2026-10-08 (~14:30Z)

At the operator's direction, all sub-agents have finished and every session shell is closed. This file is the single resume point. Read it first, then `docs/core/PROGRESS.md`. It supersedes `HALT_POINT_2026-10-07.md`.

The integration branch `feat/data-capture-and-risk` is pushed and clean at the commit that adds this file. The only unmerged work is the gate-checked AUT-6 WP1 branch (§4).

## 1. Live state at halt (keeps running)

| Item | State |
|---|---|
| Trade node | Normal 24 h cycle (16:50Z boot), `boot_family id=pm_us_crh_fq_v1`. Orders are **off**: the supervisor drop-in `fq-v1-halt-orders-off.conf` sets `BREEZY_ORDERS_ENABLED=0`, and the permit capability is `absent`. **No family trades real money.** |
| FQ v2 | **Will not trade.** `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` applies (see §3). The F6 composed veto stays fail-closed. |
| Collectors | `us-source-collector@{lamp,pfm,nbp,lav,mos,obs}`. C1-R5 (merged c9023563) is live from the primary tree. It retries a held collector lock within the work budget, and writes explicit `skipped` ledger rows. Collector health was not re-verified at halt. |
| PFM history backfill | `breezy-pfm-history-1008a` started 04:44:56Z on the pre-C1-R5 code, with `--max-runtime-s 38000`, so it ends by about **15:18Z**. Report: `~/.local/share/breezy/quarantine/run-reports-2026-10-08/pfm_history_1008a.json`. |
| Quarantine copy | `breezy-pfm-quarantine-copy-1008` waits for the backfill to exit. It then copies `/tmp/breezy-pfm-quarantine-2026-10-08/` to `~/.local/share/breezy/quarantine/pfm_2026-10-08-durable/` and writes `UNIT_EXIT.txt`. This unit replaced the closed session watcher. |
| Exec client / operator caps | Untouched. |

## 2. Merged and pushed on 10-08

Every merge had a full gate with GATE_EXIT=0, read before push.

- **C1-R4** (`_check_c1` by the five pin keys): 6acf4eee, 35334029.
- **PFM** duplicate MAX → `duplicate_day`; CDT docstring: bd974d3b.
- **LOT PFM re-ingest** applied (8,834 seen; KMDW rows 23,452 → 32,286). Spot-check vs CLI is OK: 98ef56c6.
- **Coverage batching** (journaled `coverage.json`, per-source replay): 5f376d5f.
- **C1-R5** (collector lock retry inside the work budget; `skipped` ledger kind; censor keyed on skipped rows): c9023563. The pfm measured days drop 3 → 2.
- **F5 amendments:**
  - A0 KILL frozen (43cc3e0f).
  - **A1 floor frozen as `unreachable_veto`**, frozen_sha 8756dcc4, stamp d6a339ce.
    - Binding evidence: `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` (errata E-1 and E-2).
    - M-yes G3(−0.16) = 0.2104, below 0.25.
  - **A2 not built** (moot under the ruling).
- **A1 checker R5 and provenance rule**: 64e26e0c.
- **Floor MC, E-1/E-2**: 778c86f6.
- **FQ-R8-2-UNDER-VETO** plan r2/r2.1 (converged): 1e102007.
  - Phase 1a+1b: `reachable_floor`, the writer/caller allowlist contract tests T1–T4, E-3, and §R8-2(f). F6b CANCELLED. 2efd173c.
  - Stage −1, no structural mix exclusion: d3d1d64b.
  - Stage 0 NP bound, **D1 FAIL**, with domain sign-off: 77c4f404.
  - Ruling: 211dd5a9, fd86ff30.
- **CI**: `.github/workflows/tests.yml` removed. GitHub is storage only, and all tests run locally (b8fba517).
- **AUT-6 execution decisions X-1..X-7**: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-execution-decisions_2026-10-08.md`. Row 6 is split into 6a and 6b.

## 3. RULING_FQ-v2-NO-TRADE (read the ruling itself)

FQ v2 does not trade. No A1b or A1c will be designed. AUTONOMY QUEUE row 7 is split:
- **7a** (WP1–9, inert) is OPEN.
- **7b** (WP10) is GATED.

Rows 8–12 are gated **only** at their live and proof stages.

Re-open triggers:
- **T1**: the M1-v3 read on or after 2026-12-07. This is the only live T1 route.
- **T2**: a new sender family with its own prereg. This is the structural un-gate.
- **T3**: a new US source that changes the take rate.

Review date: 2027-01-25. If it lapses, the ruling stands.

## 4. Unmerged: AUT-6 WP1 (row 6a)

- **Branch and worktree.** Branch `backlog/aut6-wp1-2026-10-08`, worktree `.claude/worktrees/aut6wp1-1008`, head 07a5fbaf.
- **Scope.** It adds:
  - the delivery proof and durable outbox (E-1), split into `alert_delivery`, `alert_outbox`, `alert_proof` and `alert_drain`;
  - the enqueue-only API (X-4);
  - the redeliver CLI and `breezy-autonomy-alert-redeliver.{service,timer}`, with a 61 s worst case and an egress row;
  - the check-alerts fix;
  - the detector catalogue literals and the closure lint;
  - the network-import pin.
- **Reviews.**
  - Architect: CONVERGED except the two vacuous controls, which are fixed in 07a5fbaf.
  - Python reviewer: CHANGES, all applied.
  - Security reviewer: FIX, all applied.
  - The coordinator accepted three test changes that pin the one X-3 `onfailure_scope` gap exactly. The architect confirmed them.
- **Gate.** The full-gate result for 07a5fbaf is recorded in §7.
- **Resume steps.**
  1. The gate is green (§7). Merge `--no-ff` into feat, run the full gate on feat, read EXIT, and push.
  2. Activate: `systemctl --user daemon-reload`, then enable and start `breezy-autonomy-alert-redeliver.timer`. Run `breezy-check-alerts` once. Confirm that a `*_check_d.json` record with `attempt_kind=alert` appears under `evidence/alerts`. LIVE means the first scheduled timer run has succeeded.
  3. Optionally run a final security re-check of C1–C3 (no-follow, egress pin, size caps). Those fixes were applied but not re-reviewed by the security reviewer.
- **Open gap (X-3).** The `OnFailure=breezy-autonomy-failed@` target does not exist until WP4/WP7. When it lands, restore the "OnFailure target in a wrapped row" assertion in `test_aut6_bwrap_rows.py` and update the three exact-gap tests.
- **Tracked for WP1b / AUT-5a.** Per-component `legacy_<component>` writer ids (X-2). Today it is a single `legacy_runtime`.

## 5. Remaining backlog (manifest `docs/plans/.plan-execute-manifests/PLAN-20261008-01.json`)

1. **PFM history.** After the unit exits:
   - check `pfm_history_1008a.json` and the durable quarantine copy;
   - re-run with the C1-R5 code until every WFO is complete;
   - keep runs outside 16:30–17:10Z.
2. **GFS MOS archive**, including KNYC, after PFM history. Use `EnvironmentFile=%h/.config/breezy/breezy.env`, about 25 requests.
3. **Full-history `--draft-scratch` smoke build** with `--nbp-root …/nbp5`. It needs about 12 GiB `--max-memory-gib`, and runs alone.
4. **`source_breaks` (PIN-R7)**, from the archive and provenance reports only, after the backfills.
5. **C1 lag evidence and freeze**, on or after about **2026-10-21**, once every C1 source has ≥14 measured days and ≥30 uncensored samples. C1-R5 censoring lowers the pfm counts. Then build the scored pair and lag twin, stages A–C.
6. **AUT-6 next WPs (row 6a):** WP2 canary, WP3 unit health (re-check the §3.8 failing-unit list first), WP3b discovery-pull memory, WP5 detector catalogue, WP9 live-proof report. WP9 scores "machinery proven" only (X-7). Row 6b waits on rows 5 and 7.
7. **Row 7a** (AUT-5a WP1–9, inert) may proceed once 6a is DONE.
8. **M1-v3**: a single read on or after 2026-12-07. Never edit its PREREG.

## 6. Delegation state

- **Grok balance is EXHAUSTED** (HTTP 402, 10-08). Run `~/.claude/bin/grok-check.sh` before any dispatch.
- The fallback used for implementation was Claude tdd-guide, because Codex cannot run the bwrap gate.
- Max **2** full gates at once. At 3 or more, the import-smoke timing budget trips.

## 7. AUT-6 WP1 gate result at halt

The full gate on 07a5fbaf, run with `--basetemp` on ~/.cache, passed: `phase1 rc=0 phase2 rc=0`, **GATE_EXIT=0** (unit `breezy-gate-aut6wp1c`). The branch is **gate-green and ready to merge**. It is NOT merged into feat, so nothing about it is live yet.
