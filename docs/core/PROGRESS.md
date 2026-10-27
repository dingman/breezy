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

### P4 live read — 2026-10-27 (coordinator; evidence in `docs/evidence/P4_LIVE_READ_2026-10-27.md`)
- **Tally:** 0 fills / 0 station-days after 3 live windows (10-25/26/27). Zero is real: durable fill store, 3 node logs (45 accepted, 42 expired, 3 cancelled, 0 OrderFilled) and the D1 artefact agree; producer fails closed.
- **Mechanism:** rests bind at the venue and re-post after the 4 h cap; every rest ends at the 02:50Z permit expiry. Zero is NOT execution: the frozen sharp replay post-filtered with every live constraint (order-count budget B≈6, 4 h GTD, ack latency, backoff) keeps 9/17 fills = 0.39/day.
- **Cause (leading):** live rests sat in the ≥100-contract-queue stratum for 99.8 % of 132 rest-hours; in-sample that stratum gave 0 fills in 988 h, all 17 fills came from <100-queue episodes (1.86 h/station-day in-sample vs 0.17 h total live). Regime test REG-1 running. **Projection:** at the live-adjusted rate the pre-registered day-21 STOP (≈11-14) is near-certain; thresholds unchanged.
- **Defects found (OPEN):** [HIGH] SEL-1 (reframed by code-architect 10-27) the live node prices from a Depth10 book that contains its OWN resting order (a NO bid shows as a YES ask; `selector.py:107-110` does not exclude it, contradicting `rule.py:94`); the replay tape never holds our orders, so when our bid is best it self-ratchets toward the cap → REPLACE → slot reallocated (same want-order rule in both, `fill_pass.py:318`/`selector.py:175-177`). Lost the one thin-queue rung live (LAX 10-26 gte79f @0.81 → REPLACED 16:56:57Z; 230 contracts printed at 0.81 at 17:10Z). Fix = subtract own resting qty at our level before pricing (blueprint in the 10-27 evidence doc). [MED] SEL-2 `reconcile.py:74-75` consumes a slot for a post that `_post` then refuses; replay (`fill_pass.py:270`) moves to the next rung. [MED] OPS-1 `breezy-score-live-trials` OOM/timeout since 10-24 (full Depth10 load over the 454 GB catalog) → portfolio-ROI report never runs; fix in flight on `fix/score-live-trials-window-scan`. [MED] permit order-count budget exhausts 30–40 min before window end (4 h cap triples orders per rest). [LOW] every create returns empty-executions AMBIGUOUS → GET clears it but fires a CRITICAL `component_degraded` per order. [LOW] retired `family-tally@pm_us_crh_v2/v4` timers fail daily on the missing scorer marker (false alerts). [PROCESS] ARM-gate `unreadable == 0` never held — one stable pre-sharp resolution row unreadable since 10-23; no waiver on record.
- **10-27 deploys:** OPS-1 merged 5b60ef24 (scorer 53 s / 1 GB, marker written); SEL-1 merged b639a015 (gate EXIT 0, 29,510) and live from the 19:18Z hand relaunch (pid 442853) — **P4 r2.2 amendment** in `P4_plan_r2.md`: fills tagged pre/post-fix, thresholds unchanged. Today's 16:50Z/16:51Z boots died on a venue-side `401 /v1/account/balances` (first 401 16:31:45Z; auth OK again 19:18:02Z) — window lost 16:52–19:18Z; cause of the 401 interval UNVERIFIED (credentials and clock unchanged). Portfolio-ROI ran for the first time since 10-24 at 17:40Z and was memory-throttled at `MemoryHigh=512M` → timeout; fix on `fix/ops-hardening-2026-10-27` with the scorer guard and the retired crh_v2 tally.
- **Routing:** Grok 402 and Codex `model_not_found` on every model (10-27) → Claude sub-agents.

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
