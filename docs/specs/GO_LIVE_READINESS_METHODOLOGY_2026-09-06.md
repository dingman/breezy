# Go-Live Readiness Baseline & Progress Methodology

Status: DRAFT v4 (2026-09-06). Designed by four independent peers plus an instrument inventory; revised after three adversarial review rounds (Claude architect ×2, Claude prediction-market reviewer ×2); Codex reviews failed on a remote tool error. Measures against PREREG v2 (`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`, BINDING, registered 2026-09-05, D0 = 2026-09-05; boundary-solver inputs pinned by `inputs_sha256` in §13, fixture table in `deploy/families/gs_boundary_pm_us_crh_v2.json`; PREREG §11's gap list is stale as of registration) and never amends it. Governed by `docs/core/PROGRESS.md` (operator control contract, standing verdicts) and `docs/core/LESSONS.md` (L-1, L-8, L-9, L-12, L-18, L-23, L-25, L-28, L-30, L-32).

## 1. Executive answer (for the CEO)

- **Breezy has been operationally live since 2026-09-05** (the 09-04 launch never connected its execution client): the trade node runs each afternoon with a live-trading permit and both operator caps present, and it has placed one real order (SFO, 09-05). It has **never filled**. On the ladder in §3 Breezy is **L2 — live-small, armed, not accruing**.
- **"Going live" is not one switch.** Two independent questions: (1) *can the bot trade every afternoon it should?* — operational readiness, a punch-list of 16 daily gates; (2) *is the strategy winning?* — the pre-registered statistical verdict. Only (2) answers "are we successfully winning the trades", and it is readable only at registered looks.
- **When will we know?** Two clocks:
  - **Structural-dead KILL** (nearest): 15 afternoon-covered, venue-listed station-days with zero fills means the trade is not being offered. Counter today **0 / 15**. With four stations clean (the venue never lists ~9 % of station-days) that is **about 4 calendar days after clean coverage starts**. Coverage has failed every day so far (09-05 reconnect storm; 09-06 recorder zombie since 09:00Z), so the clock has **not started**.
  - **Sequential edge verdict**: looks at n = 10, 20, … 160 filled takes. Observed fill rate is **0 / day**, so no date exists yet. Under the planning model (0.9–1.6 admissible trials/day, unmeasured) the first look lands **7–12 days after fills start**; an early SURVIVE is arithmetically out of reach (live boundaries come from the pinned solver at the realized information fraction, about 16 at look 1 for these break-evens; the 7.83 / 5.54 figures in the boundary file are equal-t regression fixtures), so a SURVIVE realistically needs **~n = 60, i.e. 5–10 weeks after fills start**. Absolute outer deadline **2027-02-17** (D0 + 165), a terminal look: SURVIVE only if the boundary is crossed AND ΣPnL > 0 AND no `cell_dead`; anything else, including an inconclusive interior score, is KILL (CONTINUE is illegal at that look).
- **A KILL is a legitimate, expected answer.** Three earlier families died with no edge. Either verdict ends the question; only SURVIVE leads to scaled trading, and scaling is an operator decision.
- **What blocks the next state this week is operational**: the recorder (zombie since 09:00Z, operator restart; durable fix GL-12), the 17:15Z tally reload (operator), a node relaunch so today's merged fixes become runtime (operator; GL-7 was skipped), and the GL-1 ruling (build side).

## 2. Definitions

| Term | Meaning here |
|---|---|
| **Take** | The strategy's one decision per station-day that reaches the venue (an IOC order). A zero-fill or AMBIGUOUS take is a take, **not a trial**. |
| **Trial / n** | A **filled** take that scores into the registered store: `qty == 1`, `climate_day ≥ D0`, station ∈ {LAX, MDW, MIA, SFO}, provenance `live`, settlement truth resolved. Shadow, paper, archive, Kalshi rows never count. |
| **Covered-listed station-day** | Recorder tape spans ≥ 30 min of distinct quote instants inside the station's `[12:00, 17:00)` local **standard-time** window (fixed offsets from `registry/sites.toml`, never DST: MIA −5, MDW −6, LAX/SFO −8 → 17–22Z, 18–23Z, 20–01Z) with no gap overlap, **and** the venue listed that station-day. Recorder-only by ruling; node liveness is never part of the denominator. |
| **Verdict** | The word the v2 tally prints at a registered look: **CONTINUE / SURVIVE / KILL**. The only legitimate "winning" signal. |
| **Runtime vs HEAD** | A fix merged to git is not a fix in the running node until the node is relaunched (L-23). |
| **B / O** | Build side (engineering, incl. strategy-lead rulings — PREREG §13 delegates binding to the build side) / Operator (the two reserved caps, enablement, live-process actions, sinks). |

## 3. The ladder

Entered only when every criterion is true; evidence is a named artefact, never a claim. States are monotone: operational faults never move the ladder down, they show as Axis-1 FAILs.

| State | Entry criteria | Exit |
|---|---|---|
| **L0 Build-complete** | PREREG registered (manifest `status: REGISTERED`); no-egress gate green at HEAD; operator-control census and NO-SEND guards green; `allow_short=False`. | → L1 when the node runs |
| **L1 Shadow** | Node runs, strategy observes and latches, **no** permit line in the node log, enablement absent. Shadow rows never feed a verdict. | → L2 when a permit is minted |
| **L2 Live-small, armed** | Permit line in the node log for this boot with unexpired TTL; both reserved caps present **by name** in the launch environment (values never on disk except the two caps in the operator's gitignored `operator.env`); submit path reachable. **← TODAY** | → L2.1 on first admitted trial; ↓ L1 only if the operator disables |
| **L2.1 Live-small, accruing** | ≥ 1 durable fill record **and** v2 tally `n ≥ 1` (a fill that cannot be scored does not count). | → L3 or any KILL |
| **L3 Live-evidenced** | v2 look prints **SURVIVE**: `S_k ≥ b_k^eff` and ΣPnL > 0 and no `cell_dead` and structural-dead not fired. SURVIVE closes the family's test. | → L4 by operator decision |
| **L4 Scaled** | Operator raises the two reserved knobs after L3. The terminal BCa bound and the G-02 ROI standing verdict are reported **as evidence for** that decision; the build side sets no precondition. | Circuit breakers as L2, against the new caps |

**Today = L2 armed, not L2.1**: node pid 3079058 launched 16:50:09Z with permit `ttl_s=36000`; caps and enablement named in the supervisor environment (verified 09-06); durable fills 0; v2 tally `row count: 0`, CONTINUE; one take SFO 09-05 → AMBIGUOUS → RETIRED (visibility only); covered-listed count 0.

## 4. Two axes, never blended

### Axis 1 — Operational readiness (16 gates, deterministic, daily)

| ID | Gate | Emitter (existing unless noted) | Threshold | Failure signature | Flip |
|---|---|---|---|---|---|
| A1 | Recorder connected & capturing | `journalctl --user -u breezy-quote-tape`; newest non-empty file under the live instance's `quote_tick/` | growing during every station window | `DataEngine.check_connected() == False`; 0-byte stubs | O restart; B GL-12 |
| A2 | Afternoon coverage accruing | `covered_listed_station_days_<date>.json` `count` (14:15Z, T+1 for Pacific) | ≥ 1 / day | gap overlap, < 30 min span (GL-5) | B |
| A3 | Node up through windows | `/proc/<pid>` start time + node log vs each station's local window | alive across `[12:00, 17:00)` at all 4 | launch after a window opens; session death; uncapped scope (GL-7) | O relaunch cadence |
| A4 | Permit issued this boot | node log line 1 `live-trading permit issued`, TTL | present, unexpired | absent line ≠ no permit until the emitter is proven (L-30) | B/O |
| A5 | Self-check | supervisor log `self_check result=` 17:05Z | PASS | `FAIL_SHADOW_MODE_NO_PERMIT` is SV-1 until relaunch | O relaunch |
| A6 | Runtime carries the required fixes | **proxy**: node launch time vs merge times of required fixes. B item: log boot SHA + dirty flag on node log line 1 | node launched after the last required merge | 16:50Z launch predates all 09-06 merges | O relaunch; B emitter |
| A7 | Submit intent | exec sqlite `intent/current` | RETIRED at day end, never OPEN | OPEN after an AMBIGUOUS take (GL-4) | B; O clear tool |
| A8 | AMBIGUOUS-consumed station-days | exec sqlite latch reasons per day | 0 `observation_ambiguous` consumes | 3 of 4 latched station-days on each of 09-05, 09-06 (GL-3 not yet runtime) | O relaunch |
| A9 | Subscribed rungs == venue-listed rungs at window open | **no emitter yet** (GL-8: set frozen at compose, reload clamped 21600 s) | equal sets per station | late-listed HIGH rung never subscribed → suppressed take on a covered day → **false KILL risk** | B |
| A10 | Settlement-truth ingest current | NWS CLI catalog freshness per registered station (`read_climate_day_including_corrections` resolves) | ≤ 1 day stale | fill lands but no ScoredTrial (GL-9) | B |
| A11 | Structural pin evaluated | `family_tally_v2.log` token | `MATCH` at 17:15Z | `STRUCTURAL-DEAD UNAVAILABLE … 'refused'` → counter not evaluated (fails closed) | O reload (GL-6) |
| A12 | Score → tally chain | `score_live_trials_ok_<date>`; dated v2 report | present daily, tally `ok` | SKIPPED / missing counter JSON | B |
| A13 | Alerts delivered | `BREEZY_ALERT_WEBHOOK_URL` + one delivered test | delivered sink | log-only (GL-10 deferred) | O sink |
| A14 | Host memory | `free`; unit `MemoryHigh/Max` | swap < 80 %; recorder capped | swap 100 % on 09-06; supervisor scope uncapped (GL-7) | B caps; O scope |
| A15 | Gate green at HEAD | last full `scripts/ci/run_tests_no_egress.sh` recorded per merge | exit 0 | never implied by a live read | B |
| A16 | Blockers | PROGRESS GL table, weighted CRIT 3 / HIGH 2 / MED 1 / LOW 0.5; SKIP/DEFER listed, unweighted | no open CRIT; weight trending to 0 | "closed" without merged + verified commit | B; rulings B |

### Axis 2 — Edge evidence (PREREG v2 only)

Statistic `S_k = Σ(held_i − BE_i) / sqrt(Σ BE_i(1−BE_i))`, information `I_k`, `t_k = min(1, I_k/40)`; Lan-DeMets O'Brien-Fleming spending, two one-sided α = 0.025; looks at n = 10, 20, …, 160 filled takes, replayed in real fill order; boundaries `b_k^eff / b_k^fut` computed by `scripts/analysis/crh_group_sequential_boundaries.py` at the realized `t_k` (solver inputs pinned by `inputs_sha256`, §13, printed by every tally; the JSON table is an equal-t fixture, strictly lower than live boundaries whenever BE ≠ 0.5). **SURVIVE** = `S_k ≥ b_k^eff` and ΣPnL > 0 and no stratum `cell_dead` and structural-dead not fired. **KILL** = `S_k ≤ b_k^fut`, or `cell_dead` (a stratum with n ≥ 60 that is dead), or ΣPnL ≤ −60, or the D0 + 165 terminal look unless SURVIVE's full conjunction holds there (the interior band `b_trunc^fut < S_k < b_trunc^eff` fails closed to KILL; CONTINUE is illegal), or **structural-dead** (§9: ≥ 15 covered-listed station-days with 0 fills; one fill defeats it). Between looks nothing is evidence: not PnL, not win-rate, not "five blockers closed and one good trade". Reading `S_k` off-schedule spends α the design already allocated; the tally code updates the verdict only inside the scheduled-look loop, so there is no off-schedule path to read.

### Why blending is p-hacking
Axis 1 moves *when n can accrue*; it never moves `S_k`. A CEO dashboard that adds "gates passed" to "trades won" manufactures a number with no error rate. Keep two numbers: a pass fraction and a verdict word.

## 5. Baseline scorecard — 2026-09-06 (read from artefacts, 22:40Z)

| Gate | Source | Today | Status |
|---|---|---|---|
| A1 | journal 09:00:39Z; live instance `1cdca371` = 0-byte stubs | zombie 13 h after the 09:00Z rotate restart | **FAIL** — operator restart |
| A2 | `covered_listed_station_days_2026-09-06.json` | 0 (09-05 gap-overlapped; 09-06 not captured) | **FAIL** — clock not started |
| A3 | node launched 16:50:09Z | precedes all four LST windows (MIA opens 17:00Z); pending liveness to 01:00Z | PASS (so far) |
| A4 | node log line 1 | issued 16:50:09Z, TTL 10 h | PASS |
| A5 | supervisor log 17:05Z | FAIL_SHADOW_MODE_NO_PERMIT (SV-1 false negative) | **FAIL (known-false)** |
| A6 | launch 16:50Z vs merges 21:07–22:16Z | stale (no GL-1a/2/3/6) | **FAIL** — proxy |
| A7 | exec sqlite | RETIRED / OPERATOR_CLEARED | PASS |
| A8 | latch by day | 09-05: 3 of 4 latched station-days were `observation_ambiguous`; 09-06: 3 of 4 | **FAIL** |
| A9 | no emitter | — | UNREAD (B item) |
| A10 | NWS health json `gate_state: OPEN`; per-station freshness not read | — | UNREAD |
| A11 | `family_tally_v2.log` 15:30Z | `refused`; counter not evaluated | **FAIL** — operator reload |
| A12 | `score_live_trials_ok_2026-09-06`, v2 report | present; tally `ok` | PASS |
| A13 | unit env | log-only | **DEFERRED** |
| A14 | `free -m` | swap 8191 / 8191 MiB | **FAIL** |
| A15 | full gate at `ff41370` | exit 0, 0 failures | PASS |
| A16 | PROGRESS | GL-1 3, GL-5 3, **GL-12 3**, GL-4 2, GL-6 1, GL-8 1, GL-9 1, GL-11 0.5 = **14.5**; GL-7 SKIP, GL-10 DEFER | **FAIL** |

**Axis-1: PASS 5 (A3, A4, A7, A12, A15) / UNREAD 2 (A9, A10) / DEFERRED 1 (A13) / FAIL 8 (A1, A2, A5, A6, A8, A11, A14, A16) = 16.** Convention: DEFERRED is reported separately, never folded into FAIL or PASS. Axis-2: n = 0, CONTINUE, structural-dead 0 / 15, fills 0, takes 1 (unresolved).

## 6. Read procedure (daily, ~17:20Z once GL-6 reload lands)

1. `cat` the dated v2 report, coverage JSON, and `score_live_trials_ok_<date>`.
2. Read-only sqlite: fill-key count, latch reasons for the day, intent state.
3. `grep` the node log: permit line, launch time (boot SHA once A6's emitter exists), `AMBIGUOUS`, `OrderFilled`, `create-order classified kind=`.
4. Recorder journal: connected state; newest non-empty quote file mtime inside the live instance dir.
5. Supervisor log: `self_check result=` (SV-1 until relaunch).
6. PROGRESS GL table (weighted); `free -m`; NWS catalog freshness per station.
Never run the test suite as part of the scorecard; A15 is a per-merge artefact.

## 7. Progress readouts and cadence

- **Daily (automatable):** Axis-1 pass / partial / unread / fail counts by ID; covered-listed count vs 15; fills; latch reasons; intent; permit validity; verdict word. Coverage JSON is T+1 for the Pacific afternoon.
- **Weekly (CEO):** ladder state; weighted blocker burn-down with owner; covered-listed accrued vs the KILL clock; **observed** fills/day (never the planning model); n and looks completed; earliest next-look date at the observed rate; Axis-1 pass fraction; runtime-vs-HEAD drift; operator decisions outstanding; operator-accepted risks (GL-7, GL-10) listed permanently.
- **Tooling (L-1 verdict):** every number above has one authoritative emitter. A `scripts/analysis/go_live_scorecard.py` is justified only as a zero-computation read-only compositor keyed by gate ID; it must never re-derive coverage, n, or a verdict. Decision: two weekly readouts assembled by hand from §6, then the compositor as a backlog row.

## 8. Time-to-decision arithmetic

r = filled takes per calendar day since D0 (from fill keys). Today r = 0. Rounding: ceiling (a partial day does not complete a look).

| Event | Rule | At r = 0 | After fills start (planning 0.9–1.6 / day, unmeasured) |
|---|---|---|---|
| First registered look | n = 10 | undefined | 7–12 days after the first fill |
| Realistic SURVIVE | boundary reachable ≈ n = 60 | undefined | 38–67 days (5–10 weeks) |
| Structural-dead KILL | 15 covered-listed, 0 fills | clock not started (0 / 15) | ~4 days from the first clean 4-station day (longer with ~9 % never-listed days) |
| Terminal look (truncation) | D0 + 165: SURVIVE only if `S ≥ b_trunc^eff` ∧ ΣPnL > 0 ∧ no `cell_dead`; else KILL (interior band fails closed) | 2027-02-17 | 2027-02-17 |

Days to n = 60 by rate: 0.5 → 120; 0.9 → 67; 1.5 → 40; 3.0 → 20. (PROGRESS's "38–66 d" uses floor rounding; this document uses ceiling.) Uptime shortfalls lengthen both clocks; nothing accelerates a verdict.

**Levers that shorten time without touching PREREG:** capture uptime and gap rate on the four registered stations; node uptime through every window plus a relaunch cadence so merged fixes become runtime; GL-4 (AMBIGUOUS no longer burns the day), GL-8 (late rungs subscribed — also removes a false-KILL path), GL-9 (fill chain proven on a synthetic fill), GL-12 (recorder), the 17:15Z reload. **Forbidden:** peeking `S_k`/PnL between looks; re-ruling §9 or the 15-day floor; lowering n or extending `n_max`; changing the station set, take rule, or `BE_i`; pooling shadow/paper/Kalshi rows; reclassifying zero-fill or AMBIGUOUS takes as fills; a fourth lock strategy (L-9). The Kalshi sibling is a separate family with its own clock, not prioritised until Polymarket.us fills (operator ruling 09-04).

## 9. CEO statement template (weekly, one paragraph)

> Week of {date}. Breezy is at **{L-state}**. Operational axis: {pass}/16 gates pass; the next state is blocked by {gate IDs with owner}. Pre-registered edge test: n = {n}, verdict **{CONTINUE/SURVIVE/KILL}**, structural-dead counter {c}/15 with {fills} fills. At the observed {r} fills/day the next registered look can occur no earlier than **{date or "undefined at r = 0"}**; if fills stay at zero the structural-dead rule answers first, around **{date}**. A SURVIVE is a threshold crossing at a pre-registered look, not a win-rate; a KILL is a legitimate answer that stops wasted capital. Decisions only you can take this week: {caps / enablement / relaunch / reload / sink}; {family or venue expansion}. Accepted risks on the books: {GL-7, GL-10}.

## 10. Risk register (of the methodology)

| Risk | Failure mode | Control |
|---|---|---|
| Goodhart on blockers | rows closed in git while runtime unchanged | score the runtime (A6, A8); "closed" = merged + independently verified |
| Uptime as vanity | "node up 24 h" with uncovered afternoons | A2 counts, not process existence |
| Coverage gaming | shorter window, dropped gap rule, node liveness in §9 | forbidden; §9 recorder-only by ruling |
| **False KILL from our own faults** | subscription freeze (A9) or recorder zombie (A1) suppresses takes on covered days | A9/A1 are hard gates; a KILL reached under an A1/A9 FAIL streak is **reported with the caveat but is never suspended or discounted** |
| Shadow ≠ live | paper replay takes cited as progress | provenance sidecar refuses non-live stores |
| PREREG drift | "just lower n" | new family, n resets; unilateral amendment banned |
| Operator knobs leaking | a default cap in code or docs | census test; values only in the launch shell |
| Ownership drift | rulings parked on the operator | rulings are B (PREREG §13); O = caps, enablement, live processes, sinks |
| Host limits | OOM/SIGKILL history; swap 100 %; uncapped scope | A14 daily; GL-7 recorded as operator-accepted risk, permanently visible |
| Self-check vs permit | SV-1 FAIL read as "shadow mode" | node log is the permit oracle (L-23, L-30) |
| AMBIGUOUS as fill | booking 0 on a timeout | L-32: R-7 item 5 stands until ruled |
| Compositor becomes a second n | scorecard script re-derives a verdict | zero-computation compositor only |

## 11. Decisions taken (revised after review)

D1 Ladder splits L2 armed / L2.1 accruing; intent state is an Axis-1 gate (A7), not an L2 entry condition, so the ladder stays monotone. D2 §9 denominator recorder-only; node liveness is A3. D3 Structural-dead KILL is a first-class CEO date at n = 0; the A1/A9 (recorder, GL-8 subscription) caveat is reporting-only and never suspends the rule. D4 SV-1 stays a known false negative until relaunch, then A5 is hard. D5 Weekly statement leads with the n = 10 first look and the ≈ n = 60 realistic SURVIVE (no n floor exists in the rule). D6 A15 is per-merge, never implied by a live read. D7 L4 is the operator's caps decision after L3; BCa and G-02 are evidence, not preconditions. D8 Planning rates appear only in §8 labelled planning. D9 Two manual weekly readouts before any compositor. D10 Rulings (GL-1) are build-side.

## 12. Immediate actions surfaced by the baseline

Operator rows are information for the operator's own decision; the build side neither runs them nor re-decides an operator skip (GL-7). Build rows are the coordinator's to schedule.

| # | Action | Owner |
|---|---|---|
| 1 | `systemctl --user try-restart breezy-quote-tape.service`, then confirm a new pid and a growing `quote_tick/` tree | O |
| 2 | `systemctl --user daemon-reload && systemctl --user restart breezy-pm-crh-v2-tally.timer` (GL-6) | O |
| 3 | Relaunch the trade node (the build side reports only that merged fixes are not runtime until a relaunch; whether and when is the operator's GL-7 decision) | O |
| 4 | GL-12 durable fix (retry empty discovery on initial connect; widen fail-fast to all of `_connect`; consider moving the rotate tick past ~09:45Z listing) — before tomorrow's 09:00Z rotate repeats the incident | B |
| 5 | GL-1 strategy-lead ruling (R-7 item 5 vs backlog row; GET-based resolution with GL-4) | B |
| 6 | A6 emitter (boot SHA on node log line 1); A9 emitter; A10 per-station freshness read | B |
| 7 | Alert sink (GL-10) or explicit acceptance in the weekly readout | O |

## 13. Provenance

Designs: Grok (full), Codex (full), Claude trading-bot-architect (operational axis), Claude prediction-market-reviewer (edge axis); instrument inventory with live readings: Grok; recorder incident diagnosis: Grok. Round-1 review: Claude architect (8 blocking, all adopted), Claude prediction-market-reviewer (2 blocking, adopted); Codex round 1 died on a remote 404. Round 2: Claude architect (12/14 resolved; 3 new corrections adopted: boundary provenance, LST windows, pass-count convention); Codex rounds 1 and 2 both died on a remote-compaction 404 (hard tool error); its partial notes on truncation wording and §12 ownership were adopted. Round 3: fresh Claude prediction-market-reviewer verified the boundary provenance, SURVIVE rule, §8 arithmetic and LST windows (4/5 correct); its one correction, the conjunctive D0 + 165 terminal rule with the fail-closed interior band, is adopted in §1, §4 and §8. Coordinator decisions D1–D10.
