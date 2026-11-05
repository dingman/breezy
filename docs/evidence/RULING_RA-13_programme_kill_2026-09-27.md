# RULING — EDGE-5 RA-13: programme evidenced-KILL test (SIGNED, 2026-09-27)

Authority: `EDGE-5_rearm_roadmap_plan_r4_2026-09-27.md` + AM-1..AM-4; r1 RA-13 row (:45); r2 horizon-dating rule (:239-248); AUD-18 §6.6.
Drafter: planner (blind). Peers (blind): trading-bot-architect REQUEST_CHANGES, prediction-market-reviewer REQUEST_CHANGES — both endorse the PARTIAL structure; every required edit applied in §7 (BINDING, overrides §0-§6). **Arms nothing. Sets no operator control.**
Binding, not re-litigated: forecast edge on PM.us rungs TERMINAL (09-20); programme FWER α=0.025; any statistic on post-2026-09-25 tape forfeits H-ARCHIVE-RECAL CONFIRM days; bot NOT armed, A1 halt operator-only and SET.

## 0. Trigger test (each RA-13 clause vs today)
| # | Clause (source) | Today's evidence | Verdict |
|---|---|---|---|
| T1 | RA-10 resolves REJECTED / `ABANDONED_CAP_EXHAUSTED` [VERIFIED r1:45; r4:183-185] | RA-10 never registered; RA-9 ruled `UNDERPOWERED_NOT_REGISTERED` (MDE 0.0964 > bound 0.04, n≈1743 needed, "patience cannot rescue") [VERIFIED RULING_RA-9:134-138]; RA-9b+RA-10 PARKED [VERIFIED RULING_RA-9:228]; the ruling itself names RA-13 as the honest next step [VERIFIED RULING_RA-9:231] | **NOT MET literally; MET IN SUBSTANCE for the trigger-4 path only.** Zero-look, so no alpha was spent, but no horizon or accrual can reach a look at k=1 [VERIFIED RULING_RA-9:139-143] |
| T2 | "IF NOT" CONFIRMED → RA-13 [VERIFIED r4:466-468] | r1 conditions this on AUD-18 §6.6 being independently met [VERIFIED r1:386-387] | Defers to T5 |
| T3 | RA-8 never fires within a horizon "by analogy" to archive-recal's 600 station-days [VERIFIED r1:45]; r4 "dated no-trigger horizon elapses" [VERIFIED r4:185, :466] | No horizon was ever dated. RA-8 is restricted to pre-freeze data [VERIFIED r3:94-95; r4:186] and no RA-8 unit exists under `deploy/` [INFERRED: search of deploy/ returned nothing]. HUNT-1 cites 1-6 clusters per untested hour vs a 15 floor [VERIFIED RULING_HUNT-1:19,35] | **NOT MET: horizon undated, so it cannot have elapsed.** Also flagged: under the pre-freeze restriction, trigger 1 cannot increment (L-38, LESSONS.md:1354) |
| T4 | AUD-12 unresolved past the no-trigger horizon (separate stall cause) [VERIFIED r4:466-467] | AUD-12a RULED retain-0.01 [VERIFIED RULING_AUD-12a:3]; 12b = EDGE-1, live at respawn; the RA-3 flag is still unflipped [VERIFIED PROGRESS.md:53; RULING_AUD-12a:33-35] | **NOT MET** (no horizon; AUD-12 is moving) |
| T5 | AUD-18 §6.6: every BLOCKED class had a full opportunity AND archive-recal is `ABANDONED_CAP_EXHAUSTED` or PARKED past its peer-ruled horizon [VERIFIED AUD-18:963-973] | H-ARCHIVE-RECAL is `UNDERPOWERED_NOT_REGISTERED` [VERIFIED RULING_H-ARCHIVE-RECAL:97-105; RULING_RA-9:222], so its 180-day horizon never started. H-NO-SIDE is UNDERPOWERED [VERIFIED RULING_H-NO-SIDE:93-102]. Hours 10-11 are blocked pre-registration by `OBSERVATION_GATE_UNRESOLVED` [VERIFIED AUD-18:755,757]. The EDGE-4 revival trigger (≥300 post-freeze CONFIRM station-days) is still open [VERIFIED EDGE-4_DISPOSITION:21] | **NOT MET literally.** §6.6 did not foresee every class dying at intake. The one open evidence event (EDGE-4 revival) cannot fire before ~2026-11-24 (300 / 5 station-days/day from 09-26) [INFERRED] |

## 1. Decision: PARTIAL
- **KILL (terminal, now): the PM.us trigger-4 path `H-OFFWINDOW-T4-2026-09` at k=1.** RA-9b and RA-10 go from PARKED to CLOSED for this estimand. Basis: T1 in substance [VERIFIED RULING_RA-9:136-138,228].
  - Re-open only by the route RA-9 A-9 already allows: a peer-reviewed bound revision from outcome-free pre-freeze evidence [VERIFIED RULING_RA-9:228], or a materially different estimand entering through AUD-18 [VERIFIED RULING_HUNT-1:38].
- **NOT-YET: the programme KILL of PM.us daily-high arming.** It gets a dated horizon (§3). T3/T5 are unmet, and killing now would pre-empt the EDGE-4 revival event that §6.6's "full opportunity" wording protects [INFERRED from AUD-18:963-966].
- **Why not KILL now:** it would be as unevidenced as a silent stall. §6.6's archive-recal condition is formally unmet, and a KILL now changes nothing operationally, because the bot is already not armed [VERIFIED README:3; PROGRESS.md:76].
- **Why not plain NOT-YET:** leaving RA-9b/RA-10 PARKED keeps a dead path looking alive, and building or accruing for it would only forfeit CONFIRM days [VERIFIED RULING_RA-9:228].
- **HUNT-1 is NOT killed.** It stays CRIT/GATED and BLOCKED-OPEN. A KILL of one estimand, or of PM.us arming, is never a KILL of the operator requirement [VERIFIED RULING_HUNT-1:30,43; PROGRESS.md:64].

## 2. What stays running / what stops
**Stays running (the evidence corpus other open items need):**
- Recorder quote/Depth10 capture, the AUD-09a census and nightly replay-daily. These feed the EDGE-4 revival count toward 300 post-freeze CONFIRM station-days [VERIFIED EDGE-4_DISPOSITION:21].
- Nightly `hypothesis_triage.py` 01:20Z [VERIFIED r4:202-205].
- EDGE-1 fee probe and the RA-1 A0 5-day clock [VERIFIED README:26].
- Node spawn with the A1 halt SET (never arms), v4 tally, AUD-05 / AUD-07 / AUD-10b schedules [VERIFIED PROGRESS.md:56-59,74].
- Latent-defect builds useful to ANY future look: RA-9e (merged 45c1b8f/b5256d0); RA-9d NOT built (HypothesisRecord has no horizon field; needs a schema bump), RA-8c, RA-2b + Path A zero-look UNDERPOWERED record [VERIFIED RULING_RA-9:229-230].
- Fast-track RA-1..RA-6 and EDGE-2/3/6: all are hard preconditions of any future A1-class package [VERIFIED r4:173-176; README:9-14].

**Stops:**
- RA-9b, RA-10, RA-9c2 (Path B only [VERIFIED RULING_RA-9:225]).
- Any candidate-replay unit or dev run on post-freeze tape.
- RA-11 / RA-11b / RA-12 (unreachable).
- RA-11a, if not yet started: peer question Q4.

**Firewall:** nothing in this ruling computes on tape. It forfeits no H-ARCHIVE-RECAL station-day [INFERRED; all numbers here are quoted or calendar arithmetic].

## 3. Dated horizon and re-open triggers
- **Horizon rate basis (r2 rule).** Untested hours accrue **~0.05-0.29 clusters/day** per hour, vs **up to ~2/day** in tested hours [VERIFIED r2:240-242].
  - From 1-6 clusters to the 15 floor needs 9-14 more [VERIFIED RULING_HUNT-1:19,35].
  - That is ~31-48 days at 0.29/day and ~180-280 days at 0.05/day [INFERRED arithmetic].
- **Programme KILL horizon: 2027-01-25.** That is 120 calendar days from today, the r1 analogy of 600 station-days at the nominal 5/day [VERIFIED r1:45; AUD-18/H-ARCHIVE-RECAL:52].
  - The date is firm. A shortfall in station-days from capture holes does not extend it (L-38 [VERIFIED LESSONS.md:1354]).
  - No A-5 pause applies, because nothing is registered with a look [VERIFIED RULING_RA-9:223].
- **The event that fires it:** the first nightly triage on or after 2027-01-25 with none of R1-R4 below having occurred → the coordinator issues `RULING_RA-13_programme_kill_<date>.md` (KILL) and starts Kalshi slice K-2 (§4).
- **Re-open / defer triggers (any one before the horizon pre-empts the KILL):**
  - R1: HUNT-1 trigger 1: any off-window hour ≥15 clusters. Only countable if peers lift the pre-freeze restriction (Q1).
  - R2: a live sub-degree observation source [VERIFIED RULING_HUNT-1:36].
  - R3: the EDGE-4 revival trigger fires (≥300 post-freeze CONFIRM station-days) → re-plan archive-recal within AUD-18 §6.3 [VERIFIED EDGE-4_DISPOSITION:21]. If that re-plan still fails its power check → KILL fires immediately, without waiting for the horizon [INFERRED: §6.6 full opportunity is then met].
  - R4: a new estimand that clears its power check at intake [VERIFIED RULING_HUNT-1:38].
- **No bare stop.** Trigger-4 KILL → next action: record the Path A UNDERPOWERED record (needs RA-2b). Programme NOT-YET → next action: the nightly triage + the EDGE-4 count. Programme KILL → next action: Kalshi K-2.

## 4. Kalshi roadmap item (opened by this ruling)
- **Branch:** `wip/kalshi-s4-registry`. One commit, `58280b6` ("S4 registry entries + Kalshi tally unit — PARKED"), on top of `d2faeab`, created 2026-09-04 21:32Z [VERIFIED .git/logs/refs/heads/wip/kalshi-s4-registry:1-2]. `git log -5` was not run (no shell); 23 days stale vs main, so a rebase is non-trivial [INFERRED].
- **Scope:** a sibling Kalshi family with its OWN AUD-18-shaped ledger, α budget and triage. Never pooled with PM.us [VERIFIED AUD-18:994-995; memory kalshi-lists-24-cities-all-5min].
  - Lever: 24 cities vs 5. The 19 new stations are the only independent-n lever; the shared cities are pseudo-replication [VERIFIED AUD-18:986-993; memory].
  - Caveat: settles on The Weather Company, so per-station reconciliation is mandatory [VERIFIED AUD-18:996-999].
- **K-1 (first slice, now, desk-only):** an outcome-free power-feasibility memo.
  - Station-days/day on the 19 new stations → days to n≈1743 at α 0.025/4, vs the 0.04 bound, using only the committed `docs/evidence/venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md` and `docs/evidence/kalshi_station_cadence_2026-09-04.md`.
  - No API calls, no branch edits, no runtime code, no PM.us tape (so no firewall cost).
  - Never displaces PM.us work [VERIFIED memory polymarket-us-first-kalshi-secondary:22-23,31].
- **K-2 (on programme KILL only):** rebase the branch and re-plan against `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` through the planning gate. Live enablement stays operator-only [VERIFIED PROGRESS.md:79-80].

## 5. What this does NOT decide
- It does not kill HUNT-1, NO-side hunting, or H-ARCHIVE-RECAL's revival path.
- It does not clear or touch the A1 halt, live-trading enablement, the max-daily-budget or max-per-position caps, or the NO-SEND firewall. It names them and sets none.
- It does not change AUD-12a, θ 0.0695, the 0.01 allowance, or α.
- It does not start a Kalshi adapter, transport or trading build before the horizon.
- It does not touch Nautilus. `allow_short` stays False. No test is weakened.

## 6. Open questions for the peers
- Q1: Is an outcome-blind count of liftable-quote clusters per off-window hour on post-freeze tape a "statistic" that spends H-ARCHIVE-RECAL days (README:18 says any statistic; H-ARCHIVE-RECAL:25 says the firewall binds the corpus)? If yes, trigger 1 is dead until 2027-01-25; should the ruling say so outright?
- Q2: Post-KILL, does starting K-2 conflict with the operator's "Kalshi not prioritized until PM.us working" (memory :37)? Under the 09-21 standing grant that is a peer-loop decision, not an operator one: confirm.
- Q3: Is 2027-01-25 (r1's 600-station-day analogy) right, or should the horizon be the EDGE-4 revival date plus a re-plan margin?
- Q4: Should RA-11a (permit TTL / supervisor cycle) be parked, since its only consumer is all-hours enablement?
- Q5: Does T1's "met in substance" survive the AUD-18:757 distinction between intake refusal and a spent look?


## 7. Peer-loop amendments (BINDING; override §0–§6 where they conflict)
- **B-1 (domain, CRITICAL, applies to §3 R3).** If the EDGE-4 revival fires and the archive-recal re-plan still fails its power check, the archive-recal clause of §6.6 is satisfied. That alone does **not** fire the programme KILL.
  - §6.6 also requires that NO-side hunting (H-NO-SIDE) and hours 10–11 (`OBSERVATION_GATE_UNRESOLVED`, which has no dated horizon of its own) have each independently had a full opportunity (AUD-18:755,757,963-973).
  - A failed re-plan opens a fresh peer ruling. That ruling must dispose of those classes before the §6.6 conjunction is met.
- **B-2 (domain, HIGH, applies to §4 K-1).**
  - K-1 MUST NOT reuse PM.us's n≈1743, `mde_plausibility_bound=0.04` or α=0.025/4. Each is derived from PM.us comparators and PM.us's own §6.3 class count, and archive-recal uses 0.03.
  - K-1 computes only a station-days/day accrual estimate for Kalshi's 19 new stations. It states that no MDE, bound or n-target can honestly be quoted until Kalshi has its own §6.3-equivalent triage and comparator evidence.
- **B-3 (domain Q1, ruling-grade; replaces §3 R1 and answers Q1).**
  - The firewall binds the corpus, not the statistic (README binding rules; EDGE-4 disposition). So ANY post-freeze count, outcome-blind or not, permanently spends H-ARCHIVE-RECAL CONFIRM days.
  - HUNT-1 trigger 1 therefore stays confined to the frozen pre-freeze corpus. That count cannot increase (L-38).
  - R1 is **not** an earlier re-open path. It is inert until the horizon, and is coincident with or later than 2027-01-25.
- **B-4 (domain Q5; replaces the basis clause of §0 T1).** RA-9 ran a real outcome-free power check and concluded that patience cannot rescue the design (RULING_RA-9:136-138). That is the substance. It is **not** an equation of the two AUD-18:757 gates, because `UNDERPOWERED_NOT_REGISTERED` is the power gate, not `OBSERVATION_GATE_UNRESOLVED`.
- **B-5 (architect Q3 + domain edit 5; replaces the horizon rationale in §3).**
  - **2027-01-25 is a governance calendar backstop for R2–R4.** It is **not** a measure of RA-8 accrual, because R1 is frozen (B-3).
  - The measured 0.05–0.29 clusters/day band (31–280 days to the 15-cluster floor) is context only. 120 days falls inside it.
  - The date is firm. It is not extended by capture holes (L-38), and not re-derived from outcomes.
- **B-6 (architect Q4; resolves Q4).** **RA-11a is PARKED** (not started; its only consumer RA-12 sits behind an unreachable RA-11). It reopens on any of R2–R4.
- **B-7 (architect, applies to §2).**
  - The "nothing computes on tape" claim is scoped to **this ruling's own numbers** (quoted or calendar arithmetic).
  - The kept-running AUD-05 (v4 tally, which counts live fills) and AUD-07 (m1c sweep) are **not evaluated here**. Their firewall standing is as ruled in their own authorities.
  - Follow-up **RA-13-FW**: confirm per item that neither reads post-2026-09-25 tape as a statistic, or declare its SEARCH cost, before either feeds any hypothesis verdict.
- **B-8 (Q2, both peers).** Venue prioritisation is not an operator-reserved cap, so starting K-2 after a KILL is a peer-loop decision. K-1 (desk-only) never displaces PM.us work.
- **Q3 is resolved by B-5, Q4 by B-6, Q1 by B-3, Q2 by B-8 and Q5 by B-4.** No open questions remain.
