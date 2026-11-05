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

## Operator control contract (set 2026-08-30; amended 2026-11-02) — BINDING

Three reserved controls: **maximum daily budget**, **maximum per POSITION** and **maximum per MONTH** (monthly cap = backlog #11, not yet in code).
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
- GAP-6/Kalshi S0: KILL / NO-GO (11-04, one look). Kalshi parked.
- GAP-1 forecast kill screen: PASS (11-03); LEAK-NULL discharged BENIGN_DOF.
- Prior backlog (ARM maker-sharp, MAKER S2–S5, BLOCKERS, calendar reads) is
  ARCHIVED, not scheduled: `docs/core/archive/PROGRESS_2026-10-22_pre-audit.md`.
  `arm/integration` (c614fb0b) is unmerged; P4 decides whether it is reused.
- Edge screen 11-06: NO family has recorded positive expectancy after fees; GAP-1 PASS never overlapped the tape (OOF ends 06-30, tape starts 08-30) — see docs/evidence/EDGE_SCREEN_GAP1_VS_ASK_2026-11-06.md.

---

## BACKLOG — portfolio-level ROI, nothing else (operator 2026-11-01; re-audited by trading-bot-architect + prediction-market-reviewer, merged; replaced the six-gap table 11-01; 11 items; EVERY item peer-reviewed 2× APPROVE as of 11-02 ~05:30Z, incl. the 11-02 ruling deltas)

Every item states its ROI mechanism: it earns dollars, or it is a named precondition for an item that does. Plans: `docs/plans/backlog/` (paths below); where a later `plan_rN_delta.md` exists it WINS over earlier revisions; each dir carries a `review_status.md` with two APPROVE verdicts. **Binding on every item:** Nautilus immutable; `allow_short=False`; never weaken a safety/settlement/contract/pin/NO-SEND test; never set, raise or propose a cap or q (Kelly BANNED, TSA §6.1); existing harness only except the exceptions named; PREREG frozen before any run, ONE look (L-34); FQ-R14 (SEARCH is never confirmatory).

| # | Item | ROI mechanism | Plan (reviewed) | Status / gate |
|---|---|---|---|---|
| 4 | ROI-LEDGER | Denominator for sizing, retire and scorecard; fail-closed `read_roi_for_decision` + additive schema 6 | `AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_4.md` (+e1/e2; 3 rounds python/PM/architect APPROVE) | BUILT 11-04 — merged 4a260589 + c0a509e4, binding gate GREEN, pushed; AC23(ii): live v6 run refuses ONLY on label identity (3 real families pass own gates). NOT consumer-ready: #5/#7 BLOCKED until OPS-4 clears label identity; re-check 11-05 17:52Z (session cron ce8910fd; if the session is gone, Next action (a) covers it) |
| 5 | SIZE-UNDER-CAPS (+ compound within caps) | Turns a proven edge into dollars: cap-and-depth size proposal, zero at ≤ break-even, bankroll-following under both caps; operator still owns q | `GAPS_2026-11-01/size_under_caps/` r1 + r3 + r4 + r5 deltas (r5: capital from native `Account.balance_free`) | READY — S0 §6.2.1 ruling first; #4 built; consumes #4 only after OPS-4 clears |
| 7 | AUTO-PROMOTE-RETIRE (replaces GAP-4 S3–S7) | Stops losers bleeding; removes the human bottleneck on winners; PROMOTE-ELIGIBLE never arms | `GAPS_2026-11-01/auto_promote_retire/` r1 + r2 + r4 + r5 + r6 deltas (over AUT-5 r7 + GAP-4 r1) | READY — step 0 retires the P4 maker; S0 with-guards power PASS/KILL; #4 built; consumes #4 only after OPS-4 clears |
| 8 | KALSHI-ADAPTER (K-2b) | Only station-day multiplier; upper bound only, EV unproven | `K-2a_2026-10-08/` r2 + r3 + r5 deltas | BLOCKED: #6 closed by #1 KILL (Kalshi NO-GO) |
| 9 | STRATEGY-SEARCH (standing intake) | Edge-discovery throughput; PASS → SHADOW in #7's registry | `STRATEGY_ITERATION_2026-11-01/plan_r3_delta.md` | READY — after #4, #7; X-SEARCH-INTAKE grant merge starts the 28-day clock |
| 10 | GAP-2 → GAP-3 → GAP-4 PREREG (forecast path) | Preconditions for a forecast family; only if #2 PASS | `gap2_forward_p_emitter/` r1+r2, `gap3_confidence_binned_backtest/` r1, `gap4_registered_family/` r1 | UNLOCKED by #2 PASS (holds discharged 11-03); GAP-2 §8 exception still owed; not started |
| — | CONFIRM-GET-TIMEOUT (from #3) | Every resting HOLD times out at `RESTING_CONFIRM_DEADLINE_S` = 5; venue GET latency vs deadline is unmeasured, so resting orders never confirm | none yet — needs a plan + peer loop (L-36/L-37 bind: no guard relaxed, create classification byte-unchanged) | CANDIDATE; not sequenced until ruled |
| — | NC-FIX | ROI mechanism: keeps F13's leak audit from firing on the penalty artefact (DoF-matched negative control inside F13) | plan persisted (r2) | CANDIDATE — PLANNED-HALTED 2026-11-05 (peer-reviewed plan: docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/) |
| — | GATE-RACE | ROI mechanism: parallel gate green without a flake-list entry (`test_iem_cli_fetch` vs environ-probe test on `src/breezy/__environ_probe__.py`) | plan persisted (r2) — tmp_path probe write or tail-serialise. PLANNED-HALTED 2026-11-05 (peer-reviewed plan: docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/) | CANDIDATE |
| — | K1-ANCHOR-WRITER (from #4 e2) | #7 eligibility under STALE needs a live order signal; at K=1 no `exec_par/order/` anchors are written (`breaker_watcher.py:665-692`) and no per-coid terminal-close record exists, so `n_open_anchors_without_fill` ships None | plan persisted (r2 + r3 amendment). PLANNED-HALTED 2026-11-05 (peer-reviewed plan: docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/) | CANDIDATE |
| — | L80-GUARD | L-80 Prevention names a test rejecting runtime-reconstructed literals (`+`, f-string, `join`); none exists | plan persisted (r3 + r4 amendment). PLANNED-HALTED 2026-11-05 (peer-reviewed plan: docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/) | CANDIDATE |

**OPERATOR RULING 2026-11-02 (supersedes every earlier "operator-only" clause except the caps):** the operator decides exactly three numbers — max USD spend per DAY, per POSITION, per MONTH (gitignored operator.env; never assigned, defaulted or proposed by code or agents). **Everything else is the bot's decision**, made by the machinery in this backlog: size within the caps (#5), arm/retire families (#7, incl. retiring the 0-fill P4 maker as #7 step 0), venue enablement (#8), what to test next (#9). Coordinator-owned engineering rulings (harness exceptions D1/D-2/GAP-2 §8, §6.2.1 sizing option, θ source, break-even = price + fee as the only win-rate floor) are decided through the peer loop, not by the operator. Plans #5/#7/#8 carry approved deltas for this ruling; #11 adds the missing monthly cap.

**If #1 and #2 both KILL:** honest end state = "no edge on either venue"; the backlog stops there and reports. (#2 did NOT KILL 11-03: PASS, HELD; #1 KILL 11-04 = Kalshi NO-GO; forecast path #10 is the only open edge route; stop rule not triggered.)

### Live state (pause lifted 11-02 by `/execute-backlog`; #1/#2 next stages are runs, not builds)
- P4 `pm_us_no_maker_sharp_v1` ARMED since 10-24, 0 fills; #3 census: 30/30 resting HOLDs time out at the confirm-GET deadline (mechanics, not regime) → CONFIRM-GET-TIMEOUT candidate; retire stays #7 step 0. EXEC-FOREIGN-POS A+B LIVE. HOLDOUT-END DONE d1f7e120. STRAT-DESIGN: Cards A/E KILL, D CLOSED-UNRUN.
- OPS-4: S3b 40dec67b PUSHED; acceptance FAILED at the 11-04 17:40Z ROI run — `n_labels_gated=25` (all family UNKNOWN), `GATED_IDENTITY`, breezy-portfolio-roi.service exit 1 daily since 11-02. This is now the sole blocker on #4 consumers (#5/#7). **DIAGNOSED 11-04 ~21:00Z:** label unit fails all 6 fires since S3b (11-02 05:00Z through 11-04 14:15Z) with `Errno 30 Read-only file system: /run/user/1000/breezy-studies.lock`; bwrap ro-binds the studies lock while `StudiesFlock.acquire()` opens it O_RDWR → no labels/marker written → report GATED_IDENTITY → all 25 historical FQ-ladder taker fills (ordered 10-01..10-05; same set, sha 48ce4dda, since the 10-27 report) booked UNKNOWN. Fix = OPS-4 S3c (sandbox lock writability; plan + peer loop: architect + security), then read the next fire.
- **OPS-4 S3c PLANNED-HALTED 2026-11-05 (peer-reviewed plan: docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/):** Fix = sandbox ro-bind of the studies lock (Errno 30); not executed. No verdict until the next label fire is read.
- **Routing (probed 11-04 05:40Z): Grok USABLE, Codex LIVE** (Split per L-79: Codex authors in the worktree; Claude tdd-guide gates + commits; Claude reviewers unchanged). Operator 11-02: "#N" = table row N.
- **Cycle resumed 2026-11-05 via /execute-backlog (operator).** Routing probed: Grok EXHAUSTED (402), Codex LIVE (CLI logged in; MCP server failed to connect).
- LESSONS volume gate: 37.8 KB accepted this cycle (lossless pass a9193c7b; 30 KB would cut binding Prevention prose).
- **Next action:** `OPERATOR HALT 2026-11-05 at execute-backlog Phase 4 gate (5 plans peer-reviewed, none executed). When resumed: (a) read the 11-05 17:52Z v6 ROI report (AC21/AC23); (b) execute from docs/plans/backlog/EXECUTE_BACKLOG_2026-11-05/ — OPS-4 S3c first (sole blocker on #4/#5/#7); (c) finding: zero fills since 10-05 — diagnose before #7. Routing probed 11-05: Grok EXHAUSTED (402), Codex LIVE (CLI).` One heavy job at a time; `systemd-run --user`, LimitNOFILE=524288, stall watch, re-entry per L-70.
- **Live-state watch:** 11-02 16:50Z boot-log check for 'operator caps validated DAY/POSITION/MONTH' unverified; failed oneshots breezy-label-outcomes.service / breezy-portfolio-roi.service need triage; session wakes daily 13:07Z `db1e44f2`/`fc4d504c`, 17:08Z `c45d8c0a`/`bb2925bd`.

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
