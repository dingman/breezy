# RULING: R3-VIABILITY (R3V-b): R3 NOT VIABLE (2026-10-08)

Status: ISSUED by the coordinator on 2026-10-08, after two adversarial peer reviews returned SOUND-WITH-CHANGES. A trading-bot-architect checked the domain; an architect checked governance and consistency. All required changes are applied. This is the pre-registered R3V-b screen. It was due 2026-10-01 and was run late.

## 1. The pre-registered rule
- **Sources:**
  - `docs/plans/backlog/RESOLUTION_2026-09-28/R3-VIABILITY_plan_r1_2026-09-28.md` §4 (lines 40-48);
  - amended by `R3-VIABILITY_plan_r2_delta_2026-09-28.md` §R3V-b (lines 47-61).
- **Threshold:** f_req = 300 / (r_max · D) = 300 / (4 · 120) = **0.625**.
- **Rule:** if the Wilson 95% upper bound (z = 1.96) of k/n over pre-freeze replay rows is below f_req, **R3 is ruled not viable**.
- **What counts toward n:** only rows that are COMPLETED, non-fee-void, whole-day and pre-freeze.
- **Minimum sample:** n ≥ 20; below that the result is INSUFFICIENT_N.
- **Freeze boundary:** climate_day 2026-09-25 counts as pre-freeze (`hypothesis_register.py:207`, `ARCHIVE_RECAL_RULING_DATE`, sourced at `r3_viability.py:115`).

## 2. Evidence
- **Command:** `PYTHONPATH=src .venv/bin/python scripts/analysis/r3_viability.py`, run read-only on 2026-10-08. Exit 0. Verbatim output:
  `R3_VIABILITY k=14 n=35 wilson_95=(0.2555, 0.5643) [two-sided 95% / one-sided 97.5% upper bound] f_req=0.6250 verdict=NOT_VIABLE`
- **Inputs:**
  - `~/.local/share/breezy/derived/replay/replay_results.jsonl`: 51 rows, last written 2026-09-30 16:17:38Z, not changed by the run;
  - `replay_sufficiency.jsonl`.
- **Rows dropped:**
  - 14 post-freeze rows, dropped before `fills` is read (firewall);
  - 2 fee-void rows, LAX and MDW 2026-09-01.
  - 35 + 14 + 2 = 51.
- **Rows counted:** 35 eligible rows. They split LAX 9, MDW 9, MIA 9, SFO 8, on climate days 09-17 to 09-25, with no duplicate keys. n = 35 is the whole eligible backlog (r1 §1).
- **Independent recompute:**
  - Wilson(14, 35) = (0.25551, 0.56427).
  - The upper bound is 0.061 below f_req.
  - The plan's boundary is k ≤ 16, so the verdict would only flip at k = 17.
- **Date-invariance:** the pre-freeze cutoff is fixed and the corpus has not changed since 09-30, so a run on 10-01 would give the same verdict.
- **census_provenance:** r1 §7 asks for a `census_provenance:` line. That requirement is discharged by r2 §R3-E. This screen is pre-freeze, replay-derived and MECHANISM_ONLY, and it cites no census CONFIRM count. It can only exclude R3; it can never confirm it.

## 3. Ruling
1. **R3 is NOT VIABLE.** This follows mechanically from r1 §4.
   - R3 is removed as a pre-horizon deferral trigger of `RULING_RA-13_programme_kill_2026-09-27.md` §3.
   - The EDGE-4 count itself and H-ARCHIVE-RECAL's revival path are untouched (§4).
   - The R3 blockers in PROGRESS (MECHANISM_ONLY validity, `UNDERPOWERED_NOT_REGISTERED`, the post-freeze filter) are moot and will not be built.
   - **R3V-a disposition:** the `breezy-replay-daily` timer has skipped on studies-lock contention since 2026-10-01. Five consecutive `BREEZY_REPLAY_SKIPPED_STALLED` alerts fired, and the 10-01 to 10-03 runs were skipped for having no FQ runner. No row has been appended since 09-30, an 8-day gap, so no post-freeze replay row exists. The contention comes from the exit-window study timing out while it holds `breezy-studies.lock`. AUT-6 WP3's unit disposition must repair or retire the timer, and must record this gap.
2. **The programme KILL decision is brought forward and decided: the 2027-01-25 horizon is KEPT.**
   - RA-13 §3 fires the KILL at the horizon. R3 failing does not satisfy the immediate-KILL conjunction (RA-13 §7 B-1).
   - Issuing the KILL now would be an early KILL with no evidence behind it, while the M1-v3 read (on or after 2026-12-07) is still pending.
   - **Deferral routes remaining:**
     - **R1:** inert. Under RA-13 §7 B-3, the HUNT-1 trigger-1 count is confined to the frozen pre-freeze corpus and cannot increment (L-38), so it is not a pre-horizon route.
     - **R2:** remains physically absent.
     - **R4:** a new estimand that clears intake.
     - **FQ-v2 triggers:** T1 (the M1-v3 read returns CONFIRM), T2 (a new family's prereg passes its own §4.6 floor gate, an R4-class event) and T3 (a pre-registered take-rate change from a new US source).
       - Each counts only once a ruling records its evidence before the horizon. Opening a plan does not count.
       - This ruling adds these triggers to RA-13 §3.
   - **Order on the horizon date:** on the first nightly triage on or after 2027-01-25, the coordinator first records the FQ-v2 review (`RULING_FQ-v2-NO-TRADE_2026-10-08.md`, Review date), then decides the KILL.
   - If none of these routes has fired by then, the KILL is issued per RA-13 §3, unchanged.
3. **RA-13 §4 is amended (L-32; source PROGRESS.md R3V-b row).**
   - The *re-plan* half of K-2 starts now as desk-only planning (K-2a). It produces a plan artifact through the planner and then adversarial peer review, re-planned against `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md`.
   - The branch rebase, any build, and the rest of the KILL-gated half (K-2b) stay on programme KILL only, as written.
   - Under RA-13 §7 B-8, K-2a never displaces PM.us work. It builds on `docs/evidence/KALSHI_K-1_accrual_memo_2026-09-27.md`.
   - **K-2a must cover:**
     - per-station TWC-vs-CLI settlement reconciliation, first;
     - the NBP S4-infra asset (`RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md` lines 55-56);
     - Kalshi's own ledger, α budget and triage, never pooled with PM.us;
     - no reuse of PM.us's n≈1743, its 0.04 bound or α 0.025/4. Kalshi derives its own §6.3-equivalent class count and comparators (RA-13 §7 B-2);
     - no use of post-2026-09-25 PM.us tape.
   - RA-13 §4 (as amended here, for K-2a only) and §5 still bind. Specifically: no rebase of `wip/kalshi-s4-registry`; no Kalshi adapter, transport or trading build; and no live enablement, which stays operator-only.

## 4. What this does NOT decide
- It does not touch the A1 halt, the orders-off supervisor drop-in, live-trading enablement, the two operator caps, or the NO-SEND firewall.
- It does not edit any PREREG. The M1-v3 read date and its once-only rule are unchanged.
- It does not kill HUNT-1, NO-side hunting, H-ARCHIVE-RECAL, or the EDGE-4 count.
- It does not touch Nautilus. `allow_short` stays False. No test is weakened.

## 5. Bookkeeping
In PROGRESS.md:
- Close the R3V-b row with this ruling.
- Mark the R3V-a row "40-target backfill proven 09-29; daily replay stalled since 10-01, see §3.1".
- Delete the "R3 blockers" RUN row as moot.
- Change the revival-path line to: horizon 2027-01-25 kept; live routes R4 and FQ-v2 T1-T3; K-2a desk planning open.
