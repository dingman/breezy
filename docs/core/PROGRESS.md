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
- Prior backlog (ARM maker-sharp, MAKER S2–S5, BLOCKERS, calendar reads) is
  ARCHIVED, not scheduled: `docs/core/archive/PROGRESS_2026-10-22_pre-audit.md`.
  `arm/integration` (c614fb0b) is unmerged; P4 decides whether it is reused.

---

## BACKLOG — portfolio-level ROI, nothing else (operator 2026-11-01; re-audited by trading-bot-architect + prediction-market-reviewer, merged; replaced the six-gap table 11-01; 11 items; EVERY item peer-reviewed 2× APPROVE as of 11-02 ~05:30Z, incl. the 11-02 ruling deltas)

Every item states its ROI mechanism: it earns dollars, or it is a named precondition for an item that does. Plans: `docs/plans/backlog/` (paths below); where a later `plan_rN_delta.md` exists it WINS over earlier revisions; each dir carries a `review_status.md` with two APPROVE verdicts. **Binding on every item:** Nautilus immutable; `allow_short=False`; never weaken a safety/settlement/contract/pin/NO-SEND test; never set, raise or propose a cap or q (Kelly BANNED, TSA §6.1); existing harness only except the exceptions named; PREREG frozen before any run, ONE look (L-34); FQ-R14 (SEARCH is never confirmatory).

| # | Item | ROI mechanism | Plan (reviewed) | Status / gate |
|---|---|---|---|---|
| 1 | GAP-6 S1→S3 KALSHI S0 kill screen | Only remaining step that can find a positive edge without a forecast (tail-band NO on settled history) | `GAPS_2026-11-01/gap6_sample_and_size/` r1+r2+r3 deltas + `prereg_r1.md` (frozen, sha 2073860f) | S1+S2 DONE 11-02 — B-8(a)/D-2(a) ruled (docs/evidence/RULING_gap6_b8_d2_2026-11-02.md), script `scripts/analysis/kalshi_s0.py` merged 311500d5, gate GREEN 76aeb420. NEXT: S3a one-series timing probe → full GET-only fetch under systemd (MemoryMax=2G, ~8 h, after #2's J2/J3 chain) → S3b audit → S3c verdict (one look). capture/census code = row #6 slice A |
| 2 | GAP-1 forecast kill screen | One pre-registered OOF Murphy run; KILL frees weeks of forecast work | `GAPS_2026-11-01/gap1_source_resolution/` r1+r2 delta + `PREREG_GAP1_2026-11-02.json` (frozen e648d181, stamp f86e3b76) | DONE 11-03 — one look run: overall PASS (D0 M1/M2/M3 beats-ask indicative; D-1 FAIL = no LAMP). HELD: f13 shuffled-null control fired (HELD_LEAK_AUDIT) + KNYC absent → sidecar `docs/evidence/GAP1_SOURCE_RESOLUTION_2026-11-03.md`; #10 unlock gated on LEAK-NULL + KNYC-DROP rows |
| 3 | GAP-5a create-path census | Diagnostic: is the maker's 0 fills a mechanics defect or regime fact (≈ 1 h, read-only) | `GAPS_2026-11-01/gap5_create_path_mechanics/` r1+r2+r3 deltas | DONE 11-02 merged 47d530c7 — X-dominant: 30/30 resting HOLDs hit the 5 s confirm-GET deadline; H5 UNDECIDABLE (backoff unlogged); STOP-REPORT, `5b_conditional_GO=false` (sidecar 100e902b). Spawns candidate CONFIRM-GET-TIMEOUT (row below) |
| 4 | ROI-LEDGER | Denominator for sizing, retire and scorecard; fail-closed `read_roi_for_decision` + additive schema 6 | `AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-01_r2.md` (r2.1) | READY now; no dependency |
| 5 | SIZE-UNDER-CAPS (+ compound within caps) | Turns a proven edge into dollars: cap-and-depth size proposal, zero at ≤ break-even, bankroll-following under both caps; operator still owns q | `GAPS_2026-11-01/size_under_caps/` r1 + r3 + r4 deltas | READY — S0 §6.2.1 ruling first; build after #4 and #11 |
| 6 | GAP-6 S4/S5 depth capture + census → `ADAPTER_DECISION` | Supply measurement that gates the only scale lever | same dir as #1 | after #1 ≠ KILL (capture starts after build) |
| 7 | AUTO-PROMOTE-RETIRE (replaces GAP-4 S3–S7) | Stops losers bleeding; removes the human bottleneck on winners; PROMOTE-ELIGIBLE never arms | `GAPS_2026-11-01/auto_promote_retire/` r1 + r2 + r4 + r5 deltas (over AUT-5 r7 + GAP-4 r1) | READY — step 0 retires the P4 maker; S0 with-guards power PASS/KILL; HARD dep on #11; build after #4 |
| 8 | KALSHI-ADAPTER (K-2b) | Only station-day multiplier; upper bound only, EV unproven | `K-2a_2026-10-08/` r2 + r3 + r5 deltas | after #6 GO; WB-3→WB-6→WB-4 ‖ WB-1→WB-5→WB-7; KC-n arms only after power REGISTERED + both-ledger α test |
| 9 | STRATEGY-SEARCH (standing intake) | Edge-discovery throughput; PASS → SHADOW in #7's registry | `STRATEGY_ITERATION_2026-11-01/plan_r3_delta.md` | READY — after #4, #7; X-SEARCH-INTAKE grant merge starts the 28-day clock |
| 10 | GAP-2 → GAP-3 → GAP-4 PREREG (forecast path) | Preconditions for a forecast family; only if #2 PASS | `gap2_forward_p_emitter/` r1+r2, `gap3_confidence_binned_backtest/` r1, `gap4_registered_family/` r1 | #2 PASS registered 11-03 but HELD behind LEAK-NULL + KNYC-DROP; GAP-2 §8 exception still owed |
| — | GAP-5b fixes | Realised only through a family that would otherwise be denied fills | `gap5_create_path_mechanics/` R3-1/R3-5 | CLOSED 11-02 — census X-dominant, no H1–H4/H5a CONFIRMED; not GO |
| — | CONFIRM-GET-TIMEOUT (from #3) | Every resting HOLD times out at `RESTING_CONFIRM_DEADLINE_S` = 5; venue GET latency vs deadline is unmeasured, so resting orders never confirm | none yet — needs a plan + peer loop (L-36/L-37 bind: no guard relaxed, create classification byte-unchanged) | CANDIDATE; not sequenced until ruled |
| — | LEAK-NULL (GAP-1 f13 audit) | Discharges the only objection to the sole forecast PASS (#2); gates #10 | none yet — needs plan + peer loop; outcome-blind; never touches `gap1_j3_2026-11-02/j3` | CANDIDATE |
| — | KNYC-DROP | Restores the 5th station or discloses the 4-station sample; read-only diagnosis of NBP `available_at_ns` vs anchor | none yet — needs plan + peer loop | CANDIDATE; gates #10 |

**OPERATOR RULING 2026-11-02 (supersedes every earlier "operator-only" clause except the caps):** the operator decides exactly three numbers — max USD spend per DAY, per POSITION, per MONTH (gitignored operator.env; never assigned, defaulted or proposed by code or agents). **Everything else is the bot's decision**, made by the machinery in this backlog: size within the caps (#5), arm/retire families (#7, incl. retiring the 0-fill P4 maker as #7 step 0), venue enablement (#8), what to test next (#9). Coordinator-owned engineering rulings (harness exceptions D1/D-2/GAP-2 §8, §6.2.1 sizing option, θ source, break-even = price + fee as the only win-rate floor) are decided through the peer loop, not by the operator. Plans #5/#7/#8 carry approved deltas for this ruling; #11 adds the missing monthly cap.
| 11 | OPERATOR-CONTROLS-MONTHLY-CAP | The operator's monthly loss bound that lets everything else be automated | `GAPS_2026-11-01/operator_controls_monthly_cap/plan_r1.md` | DONE 11-02 05:03Z — merged 5d2498ee + fix-forward ecb2508b (binding gate GREEN), pushed; supervisor restarted 05:03:36Z with MONTH in env (buildside mark written); binds at the 16:50Z 11-02 node launch. Reviews python/PM/security APPROVE; runbook now three caps. |

**If #1 and #2 both KILL:** honest end state = "no edge on either venue"; the backlog stops there and reports. (#2 did NOT KILL 11-03: PASS, HELD; this stop rule is not triggered.)

### Live state (pause lifted 11-02 by `/execute-backlog`; #1/#2 next stages are runs, not builds)
- P4 `pm_us_no_maker_sharp_v1` ARMED since 10-24, 0 fills; #3 census: 30/30 resting HOLDs time out at the confirm-GET deadline (mechanics, not regime) → CONFIRM-GET-TIMEOUT candidate; retire stays #7 step 0. EXEC-FOREIGN-POS A+B LIVE. HOLDOUT-END DONE d1f7e120. STRAT-DESIGN: Cards A/E KILL, D CLOSED-UNRUN.
- OPS-4: S3b 40dec67b PUSHED; acceptance `n_labels_gated=0` at the 17:40Z ROI run still unverified.
- **Routing (probed 11-03 16:35Z): Codex LIVE, Grok 402.** Split (L-79): Codex AUTHORS in the worktree; Claude tdd-guide GATES + COMMITS per worktree; Claude reviewers unchanged. Operator 11-02: "#N" = table row N.
- **Next action:** `#1 S3a timing probe → fetch (~8 h, systemd, MemoryMax=2G) → S3b → S3c; LEAK-NULL plan + peer loop can run in parallel (not a heavy job).` One heavy job at a time; `systemd-run --user`, LimitNOFILE=524288, stall watch, re-entry per L-70.
- **Live-state watch:** 11-02 16:50Z boot-log check for 'operator caps validated DAY/POSITION/MONTH' unverified; failed oneshots breezy-label-outcomes.service / breezy-portfolio-roi.service need triage; session wakes daily 13:07Z `db1e44f2`/`fc4d504c`, 17:08Z `c45d8c0a`/`bb2925bd`.

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
