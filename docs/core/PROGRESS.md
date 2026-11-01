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

## BACKLOG — the six gaps to the single objective (operator 2026-11-01: "the bot executes winning trades"; replaced the audit-path table 11-01)

Objective: realised win rate > price + fee, proven (operator preference ≥ 70% where price allows; size q operator-owned). Plans + `review_status.md` per gap under `docs/plans/backlog/GAPS_2026-11-01/`; every plan carries two APPROVE verdicts (architect + domain reviewer); where a `plan_r2_delta.md` exists it wins over `plan_r1.md`. Order = dependency order. **Binding on every item:** Nautilus immutable; `allow_short=False`; never weaken a safety/settlement/contract/pin/NO-SEND test; never set an operator cap; existing harness only except the exceptions named below; PREREG frozen before any run, ONE look (L-34).

| # | Gap | Improves | Plan (reviewed) | Status |
|---|---|---|---|---|
| 1 | GAP-1 SOURCE-RESOLUTION | Does any source (LAMP/PFM/GFS-MOS blends via F13 J2+J3) out-resolve NBP on < 07-01 OOF rows; KILL stops the forecast programme | `gap1_source_resolution/plan_r1.md` + `plan_r2_delta.md` (architect+PM APPROVE r2) | READY — needs S0 PREREG_GAP1 + operator D1 (one read-only reader `gap1_oof_murphy.py`) |
| 2 | GAP-2 FORWARD-P-EMITTER | Per-rung forward p_yes CSV for [10-02, T), look-ahead strict, GAP-3 contract | `gap2_forward_p_emitter/plan_r1.md` + `plan_r2_delta.md` (architect+python APPROVE r2) | BLOCKED-ON-OPERATOR — §8 exception to the 10-21 ruling (§3 items 1–6 only); after GAP-1 PASS |
| 3 | GAP-3 CONFIDENCE-BINNED-BACKTEST | `market_calibration_scan.py --forecast-p` edge bins; default byte-pinned; explore gate `p_one_sided × K_cum ≤ 0.05` AND LB > m | `gap3_confidence_binned_backtest/plan_r1.md` (architect+python APPROVE r1) | READY-AFTER-2 (pin commit first) |
| 4 | GAP-4 REGISTERED-FAMILY | PREREG v2 centred score, LD-OBF α=0.025 looks/10 fills, `LadderEvConfig` override, one forward look → ready-to-arm qty 1 | `gap4_registered_family/plan_r1.md` (PM+architect APPROVE r1) | READY-AFTER-3 (+5 for mechanics) |
| 5 | GAP-5 CREATE-PATH-MECHANICS | Evidence-first census of H1–H5 (AMBIGUOUS latch on resting creates, 46% denied 11-01); X1–X3 exits; H5a client backoff only, latch out of scope | `gap5_create_path_mechanics/plan_r1.md` + `plan_r2_delta.md` (security+architect APPROVE r2) | READY — parallel; step 0 citation closure, then census |
| 6 | GAP-6 SAMPLE-AND-SIZE | Kalshi S0 tail-band history gate (fee-free excess) → 14-day depth census → n_req 385 vs S×H; θ verification; size math illustrative only | `gap6_sample_and_size/plan_r1.md` + `plan_r2_delta.md` (PM+architect APPROVE r2) | READY — parallel; needs S1 B-8 ruling + operator D-2 (`s0`+`census` exception), D-3 (θ source) |

**Operator decisions open:** (a) GAP-2 §8 exception; (b) GAP-1 D1; (c) GAP-6 D-2/D-3; (d) size q (never proposed by the bot); (e) P4 maker: let it STOP at day 21 (≈ 11-14) or disarm now; (f) literal 70% floor vs break-even = price + fee.

### Live state (no build owed; OPERATOR PAUSE 11-01 19:55Z — wakes read-only until directed)
- P4 `pm_us_no_maker_sharp_v1` ARMED since 10-24, 0 fills; 11-01: 80 posts, 46 denied (AMBIGUOUS latch), 34/34 creates 200/empty-executions → GAP-5. EXEC-FOREIGN-POS A+B LIVE (10-30). HOLDOUT-END DONE d1f7e120 (pushed 19:21Z 11-01). STRAT-DESIGN: Cards A/E KILL, D CLOSED-UNRUN; PM.us prize ≈ $0 at qty 1.
- OPS-4: S1 PUSHED, S3 enabled 05:08Z 11-01, first fire FAILED `not_under_unit` → S3b 40dec67b PUSHED 16:48Z; next fire 05:00Z 11-02 checked at wake `c8f0b6e2` 05:13Z (record MemoryPeak; acceptance `n_labels_gated=0` at the 17:40Z ROI run). Routing: Grok 402, Codex `model_not_found` → Claude sub-agents.
- **Next action:** operator rules (a)–(f); then GAP-1 S0/S1 and GAP-5 step 0 in parallel. Wakes: `c8f0b6e2` 05:13Z 11-02, daily `db1e44f2`/`fc4d504c` 13:07Z, `c45d8c0a`/`bb2925bd` 17:08Z (session-only).

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
