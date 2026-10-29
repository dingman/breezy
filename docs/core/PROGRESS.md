# Breezy — Progress and Backlog

**This file tracks OPEN state only.** Closed work, resolution narratives and
evidence summaries do not live here. They live in git history,
`docs/evidence/`, and `docs/core/archive/`.

## Maintenance contract (BINDING, enforced)

Hard budget **250 lines / 12 KB** (`.claude/hooks/progress-size-gate.sh`);
consolidate when it blocks, never raise it. An item LEAVES this file when it
closes — the commit is the record. Never restate evidence (link
`docs/evidence/`) or durable rules (`docs/core/LESSONS.md`). Severity tags mark
OPEN items only. Rationale L-5; pre-shrink copy in `docs/core/archive/`.

---

## Operator control contract (set 2026-08-30) — BINDING

Two reserved controls: **maximum daily budget** and **maximum per POSITION**.
They live ONLY in the operator's gitignored `operator.env`, present by NAME in
the supervisor/node env, enforced per grant by `DailySpendLedger.authorize_order_cost`
(`operator_controls.py:348`; process-local, re-seeded at boot from durable fills via
`exec/client.py:2214`). The three session ceilings derive from the two caps at
permit mint (`safety.py:552-608`). Everything else is build-side.

## Standing verdicts that gate future work

- **Audit 2026-10-22** (`docs/evidence/AUDIT_independent_2026-10-22.md`): taker
  falsified live (34 fills / 4 wins / −2.63; Σprice 6.36 expected wins); maker-sharp
  17/17 is an in-sample nomination (LB 0.839 < breakeven 0.865–0.888); PM.us ceiling
  ≈ $10–65/month even with an edge. Primary failure = edge, compounded by process.
- **P4 ARMED 10-24 13:08Z**: `pm_us_no_maker_sharp_v1` is the only sending family from the
  16:50Z launch; the FQ v1 orders-off drop-in is backed up, not deleted (rollback = restore it).
- Prior backlog (ARM maker-sharp, MAKER S2–S5, BLOCKERS, calendar reads) is
  ARCHIVED, not scheduled: `docs/core/archive/PROGRESS_2026-10-22_pre-audit.md`.
  `arm/integration` (c614fb0b) is unmerged; P4 decides whether it is reused.

---

## BACKLOG — Shortest credible path (operator 2026-10-22: "replace the backlog … simple is often better")

Plans: `docs/plans/backlog/AUDIT_PATH_2026-10-22/P<n>_plan_r<N>.md` (peer reviews in
`reviews/`). Strict order; a FAIL ends the chain at that item. The plan is the
pre-registration — thresholds never move after data is read.

**Binding on every item.** Nautilus immutable; `allow_short=False`; never weaken a
safety, settlement, contract or NO-SEND test; never set or invent an operator cap;
simplest change that answers the question — no new harness, unit, ledger or ruling
unless the plan names why.

| # | ID | Work | Cost | PASS | FAIL / STOP | Status |
|---|---|---|---|---|---|---|
| 1 | P1 | Latency pre-flight on the sharp maker replay | — | — | — | **PASS** 10-22 (`docs/evidence/P1_latency_preflight_2026-10-22.md`; G0 exact set 17 / 1.96 at 8de5ebd4 on `design/maker-nobid-2026-10-21`; G1 `sharp_l1` 17 stress fills, 0 losers; L=5 s 16/16) |
| 2 | P2 | NBP p vs venue ask at the 16:50Z D−1 launch | — | — | — | **FAIL** 10-22 (`docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`; YES P&L −0.053/take, n 150, UB −0.008; D_res −0.023; independent PMR TRUSTWORTHY-WITH-CAVEATS). P2-DEL closed: keep FQ v1 dormant behind the orders-off drop-in, no deletion (`P2DEL_impact_check_r1.md`) |
| 3 | P3 | Venue probe: ONE qty-1 GTD rest at $0.01 for 4 h | ≤ $0.01 | NEW to G−30 s, EXPIRED at G+60 s, echo ±1 s | CLAMPED / EARLY / LATE → multi-hour resting unsupported | **PASS** 10-23 (`docs/evidence/P3_GTD_PROBE_2026-10-23.md`; order D947ECW011MQ NEW at confirm/mid/G−30, EXPIRED at G+60 s, echo ≤1 s, no fill, account clean; run from 061856dd on `arm/b2-control`). Licenses a 4 h live GTD only |
| 4 | P4 | Live qty-1 maker bids, sharp as built on `arm/integration`, live GTD capped at 4 h, existing caps (needs P1 + P3 PASS) | ≤ ~$21 lag-bounded | ≤ 1 loss in the first 37 settled station-days (p0 0.8747) AND net > 0 | 2nd loss = FAIL; < 8 station-days by day 21 or day 75 = STOP | ARMED 10-24 13:08Z — feat 83b138b6 (full gate EXIT 0, 29138 passed); drop-in moved to `~/.config/systemd/user/dropin-backups/`, supervisor restarted (orders on, sending family sharp); loss-stop PASS 13:09Z; first live node = 16:50Z launch (D0 2026-10-25). 16:50Z node CHURNED: LiveClock timers ran on a non-kernel thread, the thread-confined halt-veto read raised (`fq_halt_veto_unreadable`) and the strategy cancelled every rest each 30 s (39 submitted, 81 denied, 0 fills); node stopped 17:24Z. Fix ed888605 (hop clock callbacks onto the kernel loop; full gate EXIT 0, 29141 passed); hand-relaunched 18:56Z under the first-boot permit ceiling: permit + `enabled=True reason=ok`, 4 rests (sfo/lax/mia/mdw, NO @ 0.89, GTD 4 h), 0 cancels, 0 veto errors over 5 min. Follow-ups CLOSED 10-24 22:20Z: autonomy OnFailure target template `breezy-autonomy-failed@.service` never existed (alerts dropped) — shipped aec552b6, installed + daemon-reload; truth-fetch LAX 10-22 72→71 (later FINAL KLOX 232344 + catalog agree) promoted via the new reviewed `iem_cli_fetch.py promote` path (84eba08b + c29bb74c), refetch exit 0 all 5 stations. Full gate 7f438daa EXIT 0, 29164 passed |
| 5 | P5 | Scale decision (only if P4 PASS) | operator | projected net clears operator hurdle | PM.us capped at tens of $/month → Kalshi question | READY — `P5_plan_r2.md` (+r2.1); one formula vs the operator hurdle |

### P4 live read — 2026-10-27/28 (coordinator; evidence `docs/evidence/P4_LIVE_READ_2026-10-27.md`, `_2026-10-28.md`)
- **Tally (12:50Z 10-28):** 0 fills / 0 station-days after 4 windows; zero is real (durable store, node logs, D1 artefact agree). Not execution: constrained replay keeps 9/17 fills. Cause: thin-queue opportunity ÷3 since 10-13, disagree rungs 0/day since 10-17 (regime) + SEL-1 (own order in the pricing book; fixed b639a015, live 10-27 19:18Z, **0 REPLACED cancels since** vs the prior self-ratchet). **Projection:** day-21 STOP (≈11-14) near-certain; thresholds unchanged; P4 runs on (r2.2 amendment: fills tagged pre/post fix).
- **Premise reassessment (10-28, trading-bot-architect, 5 candidates):** nothing on PM.us is worth designing before the ruling; LAT-1 Stage 0 (built, outcome-free, prize ≈ $0.03/day, prereg UNFROZEN) is a closure item at the ruling, not now; early regime STOP is a permissible r2.3 amendment but buys nothing (qty 1, no successor) → not filed. At the ruling: P5/Kalshi question to the operator (C5 = read-only Kalshi P2 analogue).
- **INCIDENT 10-28 20:19Z [HIGH, FIX IN FLIGHT]:** venue added `estimatedAmount`/`estimatedCommission`/`principal` to the Order object (null on unfilled rests); strict mapper refused the 30 s resting poll ×285 → `resting_query_unreadable` latched 20:20:22Z → every re-post denied to 02:50Z. Two handling defects: poll WARN dropped the names-only key tree; the latch clears only on a readable poll of the SAME id, and the cancel path (which retired all 5 rests via tolerant zero-fill reads) never informs it → stuck for the process (L-48 updated). Fix branch `fix/order-shape-drift-2026-10-28`: 7-name drift allowlist + `WIRE_ORDER_KEYS` (27) + `ORDER_SHAPE_DRIFT_2026-10-28.md`; `_clear_resting_cancel_latch` → `_note_resting_poll(readable=True)`; poll WARN logs `str(exc)`; client byte re-pin. STATUS: MERGED e5cdf116 (serial gate 29,531 passed + 3 pin re-pins; parallel gate GREEN 29,767 ids, proof OK) and LIVE from the 23:45:48Z hand relaunch (pid 1831147) — but see the OPERATOR item: live confirmation of the mapper fix is pending the first boot that can post. First-fill checklist: record value-free types of the three fields; decide whether `estimatedCommission` joins the fee-drift watch.
- **Lost windows:** 10-27 16:52–19:18Z (venue 401 on balances, transient, cause UNVERIFIED); 10-28 20:20–02:50Z (incident). Both covered recorder days.
- **Defects OPEN:** [MED] OPS-4 ROI `GATED_IDENTITY n_labels_gated=25` = marker absent because `breezy-label-outcomes` was never promoted (TE-1 r3.3 WP-C shelved 10-12; AUT-6 notifier + production `UnitWiring` DONE; OPEN: measured `label_run --measure-peak` budget, unit move + score-live-trials 14:15→13:55 swap + tests `test_aut2_units_deploy/test_deploy_timer_hours/test_aut2_slot_guard/test_aut2_units_no_expected_failure`). Acceptance: report reproduces audit 34 fills / 4 wins (Σcost 6.36, payout 4.00; fee recompute UNVERIFIED) with `n_labels_gated=0`. [MED] OPS-2 maker writes no `no_ladder_maker/trial/*` latch keys → scorer/ROI attribute a sharp fill only via ledger. [MED] SEL-2 `reconcile.py:74-75` spends a slot on a refused post. [MED] permit order-count budget exhausts 30–40 min before window end (design consequence of caps; not to change). [LOW] AMBIGUOUS→GET `component_degraded` CRITICAL per order (4–5/day). [PROCESS] ARM-gate `unreadable == 0` never held; no waiver on record.
- **Routing:** Grok RESTORED 10-28 (probe exit 0; used for the code read + both fixes, verified against the diff); Codex `model_not_found`; Claude sub-agents otherwise. L-67: probe the route first.
- **[HIGH] EXEC-FOREIGN-POS — operator ruling 10-29 (bot ignores the operator's manual venue activity; Nautilus is the only executor).** Plan `docs/plans/backlog/EXEC_FOREIGN_POS_2026-10-29/plan_r3.md` (5×APPROVE). **Stage A (positions + shared predicate) LIVE since the 16:50Z boot 10-29 — KEEP:** e7fcec7c code / f0b83090 pins / 516efc00 gate classification, gate GREEN (29,639 passed); pre-registered prediction (5265d507) matched the boot token for token: `instrument_absent=0 foreign=1 refusals=0`, one `EXEC_FOREIGN_MARKET kind=position`, 0 `resting poll: the read did not map`, latch cleared (`docs/evidence/P4_LIVE_READ_2026-10-29.md`). OPEN item 6 rests bound: 0 `MAKER_POST` by 17:49Z (69 empty-book quote refusals, no order-intent denial) → close at the 13:07Z D1 read. **Stage B (open orders: DAY admission, never-arm gate, trial_day_latch, TIF-drift note) BUILDING** — Grok on the primary tree from 17:55Z 10-29 (brief session scratch `grok_efp_b/brief.txt` + addenda), branch `fix/exec-foreign-pos-b-2026-10-29`, then 4 blind read-only reviews → Commit A/B (pins incl. C7 row 236) → ff-merge → full gate → push on EXIT 0; activates at the next boot. Until then a manual DAY order still latches `boot_sweep_reread_failed`.
- **Cycle 10-29 IN FLIGHT (session from 03:06Z; detail in memory `exec-foreign-pos-build-2026-10-29`):** routes Grok USABLE / Codex `model_not_found` → Claude sub-agents as independent reviewers. Boot read 17:49Z: node pid of the 16:50Z boot writing, previous log ends DISPOSED, ERROR 59 all known data-side kinds, `PrivateReadRefused`=0 (auth OK), 0 fills. Re-entry: `bb2925bd` 17:08Z daily (Stage B pipeline progress / gate / push), `fc4d504c` 13:07Z daily (D1 read → close Stage A item 6, Stage B boot read once merged); session-only, expire 11-05. P4 day-21 ruling ≈ 11-14. Then OPS-4 label-unit promotion (`portfolio-roi-run.sh:41-43` claims exit 0 on the gate but `:143-144` passes exit 1 through — fix with the promotion); then SEL-2. [OPS-5 MED] host timer still owed.

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
