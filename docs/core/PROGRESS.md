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
| 4 | P4 | Live qty-1 maker bids, sharp as built on `arm/integration`, live GTD capped at 4 h, existing caps (needs P1 + P3 PASS) | ≤ ~$21 lag-bounded | ≤ 1 loss in the first 37 settled station-days (p0 0.8747) AND net > 0 | 2nd loss = FAIL; < 8 station-days by day 21 or day 75 = STOP | ARMED 10-24 13:08Z (feat 83b138b6; drop-in backed up in `~/.config/systemd/user/dropin-backups/`; rollback = restore it). Churn fix ed888605 + OnFailure template aec552b6 + LAX truth promote 84eba08b/c29bb74c all live; last full gate 7f438daa EXIT 0 |
| 5 | P5 | Scale decision (only if P4 PASS) | operator | projected net clears operator hurdle | PM.us capped at tens of $/month → Kalshi question | READY — `P5_plan_r2.md` (+r2.1); one formula vs the operator hurdle |

### P4 live read — 2026-10-27/28 (coordinator; evidence `docs/evidence/P4_LIVE_READ_2026-10-27.md`, `_2026-10-28.md`)
- **Tally (12:50Z 10-28):** 0 fills / 0 station-days after 4 windows; zero is real (durable store, node logs, D1 artefact agree). Not execution: constrained replay keeps 9/17 fills. Cause: thin-queue opportunity ÷3 since 10-13, disagree rungs 0/day since 10-17 (regime) + SEL-1 (own order in the pricing book; fixed b639a015, live 10-27 19:18Z, **0 REPLACED cancels since** vs the prior self-ratchet). **Projection:** day-21 STOP (≈11-14) near-certain; thresholds unchanged; P4 runs on (r2.2 amendment: fills tagged pre/post fix).
- **Premise reassessment (10-28, trading-bot-architect, 5 candidates):** nothing on PM.us is worth designing before the ruling; LAT-1 Stage 0 (built, outcome-free, prize ≈ $0.03/day, prereg UNFROZEN) is a closure item at the ruling, not now; early regime STOP is a permissible r2.3 amendment but buys nothing (qty 1, no successor) → not filed. At the ruling: P5/Kalshi question to the operator (C5 = read-only Kalshi P2 analogue).
- INCIDENT 10-28 (venue added 3 Order fields → `resting_query_unreadable` latch) FIXED e5cdf116, LIVE since 23:45Z 10-28 (L-48). OPEN residue: live confirmation of the mapper fix needs the first boot that posts; first-fill checklist: record value-free types of the three fields; decide whether `estimatedCommission` joins the fee-drift watch.
- **Lost windows:** 10-27 16:52–19:18Z (venue 401 on balances, transient, cause UNVERIFIED); 10-28 20:20–02:50Z (incident). Both covered recorder days.
- **Defects OPEN:** [MED] OPS-4 ROI `GATED_IDENTITY n_labels_gated=25` = marker absent because `breezy-label-outcomes` was never promoted (plan r2 READY, see cycle line). Acceptance: report reproduces audit 34 fills / 4 wins (Σcost 6.36, payout 4.00; fee recompute UNVERIFIED) with `n_labels_gated=0`. [MED] OPS-2 maker writes no `no_ladder_maker/trial/*` latch keys → scorer/ROI attribute a sharp fill only via ledger. [MED] SEL-2 `reconcile.py:74-75` spends a slot on a refused post. [MED] permit order-count budget exhausts 30–40 min before window end (design consequence of caps; not to change). [LOW] AMBIGUOUS→GET `component_degraded` CRITICAL per order (4–5/day). [PROCESS] ARM-gate `unreadable == 0` never held; no waiver on record.
- **Routing:** Grok RESTORED 10-28 (probe exit 0; used for the code read + both fixes, verified against the diff); Codex `model_not_found`; Claude sub-agents otherwise. L-67: probe the route first.
- **[HIGH] EXEC-FOREIGN-POS — operator ruling 10-29 (bot ignores the operator's manual venue activity).** Stage A LIVE, MET (`docs/evidence/P4_LIVE_READ_2026-10-30_D1.md`). Stage B MERGED 284cff57, activates at the 16:50Z boot 10-30. Acceptance (17:08Z wake): `instrument_absent=0 foreign=F refusals=0`, 0 `boot_sweep_reread_failed`, 0 `resting_query_unreadable`; manual DAY order → one `kind=open_order` notice + `STARTUP_OPEN_ORDER_NON_WEATHER_KEY`, gate not refusing; none → UNEXERCISED. Pre-boot probe 16:05Z (snapshot = gate-green HEAD) predicts first; weather-slug OPEN ORDERS at 16:05Z are the bot's own DAY rests (node runs to 16:40Z): not a stop; only a weather POSITION Breezy did not open stops. Residual: live open-orders capture for the TIF-drift note. [MED] EXEC-OWN-REST-NOISE: `startup_open_orders_present` ERROR counts the bot's own bound rests which the gate exempts (`client.py:7155-7165` vs `:6834-6852`) → exclude own rests from `counted`; client.py only, byte re-pin. **[HIGH] ALERT-4XX — webhook DAILY QUOTA (~248/day) burned in the first 2 h of each UTC day by per-order `MAKER_ORDER_DENIED` WARNs + the 5-min drain; every CRITICAL fails after.** Plan r3 `docs/plans/backlog/ALERT_4XX_2026-10-30/plan_r3.md` (cause decider + 5 reviews; section 10 binding): (d) per-(instrument, day) dedupe of non-CRITICAL denials, (a) `http_status` in failure rows, (b) ONE global `webhook.backoff` (alert_outbox writer; 300 s→30 min; probe when due), CRITICAL-first drain order, summary tokens; re-pin aut2.label + aut6.health once. Next: convergence check on section 10 → Grok build after the 17:08Z boot read → reviews → gate → push; precedes OPS-4 S0. [MED] ALERT-NO2XX health check (no webhook 2xx in N h); [LOW] ALERT-SINK-PER-CALL (`strategy.py:977` new httpx client per denial).
- **Cycle 10-30 (13:07Z wake) CLOSED 16:05Z (external event pending = 16:05Z probe, 16:50Z boot):** Grok USABLE / Codex `model_not_found`. **OPS-4 plan r2 READY** (`docs/plans/backlog/OPS4_LABEL_PROMOTION_2026-10-30/plan_r2.md`, 4 reviews converged): S0 live `label_run --measure-peak` in a quiet window after the 17:40Z scorer exits (STOP unless derived MemoryMax ≤ 4 GiB and 1800 ≥ 1.75 × wall) → S1 build on a branch → S2 reviews + re-pin + gate → S3 ff + link + enable + daemon-reload in ONE step inside 04:30–13:55Z (first 10-31). Re-entry: `72885041` 16:05Z 10-30 one-shot (tree clean at gate-green ≥3363d274 by 16:30Z; pre-boot probe incl. open orders; write the prediction), `bb2925bd` 17:08Z daily (Stage B boot read → `docs/evidence/P4_LIVE_READ_2026-10-30.md`; then ALERT-4XX build; then OPS-4 S0), `fc4d504c` 13:07Z daily; expire 11-05. P4 day-21 ≈ 11-14; then SEL-2; [OPS-5 MED] host timer owed.

- **Cycle 10-30 (16:05Z one-shot) — pre-boot probe GO, prediction pre-registered 16:10Z** (scratch `~/.local/share/breezy/scratch/session-2026-10-30/preboot_probe/`, snapshot 87065dad, no non-docs drift since 284cff57, tree clean): positions 200, 0 rows, `eof=True`; open orders 200, envelope known, parse OK, n=0 (no own rests, no manual order → TIF-drift note still unfed). **Predicted 16:50Z boot: `instrument_absent=0 foreign=0`, 0 `EXEC_FOREIGN_MARKET` lines, 0 `kind=open_order` WARNs**; F=0 branch → acceptance = boot items 1, 3, 4 (+Step 0); item stays OPEN until a boot with `foreign>=1`. Stop rules R14/R2/R18/R13/R7: none hit. Route: Grok USABLE (exit 0); Codex probe hung >60 s (unusable this cycle); Claude `polymarket-us-discovery` for the probe. Also open: `breezy-portfolio-roi.service` FAILED exit 1 since 17:41Z 10-29 (triage in flight). ALERT-4XX plan CONVERGED with r3.1 deltas (section 11, 761b8bd2) → build next. `breezy-portfolio-roi.service` exit 1 = OPS-4 by design (`portfolio_roi_report.py:4755-4757` gated-label exit → wrapper FAIL → `unit_health_unit_failed` CRITICALs, feeding ALERT-4XX; first 10-28 17:41Z). **Cycle CLOSED 16:15Z, external event pending = 16:50Z boot.** Re-entry armed (session crons, expire 11-06): `c45d8c0a` 17:08Z daily (next fires 17:38Z 10-30: boot read vs this line → ALERT-4XX build → OPS-4 S0), `db1e44f2` 13:07Z daily.

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
