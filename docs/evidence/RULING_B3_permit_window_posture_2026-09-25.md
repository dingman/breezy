# RULING — B3: permit window posture

Status: RULED — peer 1 (trading-bot-architect) ruling, countersigned by security-reviewer per AUD-02 B3 charter (`AUD-02-COMPLETION-PLAN-2026-09-25.md` §2 B3).
Read-only; no code, no store write, no order-path change.

**Slug:** `B3_permit_window_posture` · **Date:** 2026-09-25 · **Author:**
trading-bot-architect (peer 1, BLIND run)

## 1. Question ruled

`POST_FORECAST_PHASE_2026-09-20.md` row B3 (`:48`), narrowed by Amendment A-1
(`:103-118`, striking option (b) — a second daily process/mint, a de facto
~20h/day authority window) and Amendment B-3 (`:298-310`: B3 must precede B1 —
the 02:50Z→16:40Z window is the *designed* single-mint posture, not a fault,
so B1 must not alert on it until B3 rules). Options: **(a)** accept the gap,
documented and unalerted until B1 exists; **(a′)** move LAUNCH later. Out of
scope: the mid-day relaunch re-mint bound, ruled separately by
security-reviewer as "permit cumulative coverage"
(`docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`, being
implemented) — cited by name only, not re-litigated here.

## 2. Evidence (re-read directly)

- `safety.py:172` — `PERMIT_TTL_NS = 10*60*60*1_000_000_000` (10h; pinned by
  `test_the_permit_ttl_is_pinned_to_ten_hours`).
- `safety.py:675-739,714` (`issue_live_trading_permit`) —
  `expires_at_ns = issued_at_ns + PERMIT_TTL_NS`; one caller.
- `app/trade.py:651` — `permit = issue_live_trading_permit(clock=LiveClock())`,
  the sole per-boot mint site.
- `trade_supervisor_core.py:33-35` — `STOP_PRIOR_UTC=16:40`,
  `LAUNCH_UTC=16:50`, `SELF_CHECK_UTC=17:05`.
- `trade_supervisor_core.py:54-55` — `MIDDAY_MAX_RELAUNCH_ATTEMPTS=3`,
  `MIDDAY_MIN_RELAUNCH_GAP=5min`.
- `trade_supervisor_core.py:864-868` (`midday_watch_window_end`) — closes
  01:00Z on trading_day+1.
- `trade_supervisor.py:1352-1379` — a mid-day relaunch spawns a NEW
  `breezy-trade` process (`ports.spawn`, `:1377`), which mints a NEW permit at
  its own boot (`app/trade.py:651`) — confirms relaunch = a second mint, not
  a re-use.
- `R8_OPERATOR_RUNBOOK.md:138-140` — TTL retargeted to bracket "the union of
  the four decision windows[,] 17:00 UTC → 01:00 UTC next day, plus 1h slack
  each side" — the four station entry windows ([12:00,17:00) LST at
  LAX/MDW/MIA/SFO, `PREREG_v1` §7) converted to UTC.

## 3. Numbers (independently re-derived)

- **Nominal single-mint:** 16:50Z → 02:50Z (10h). **Gap** to next STOP_PRIOR
  (16:40Z) = **13h50m**.
- **Worst-case multi-mint, WITHOUT the cap:** a mid-day relaunch at 00:59Z
  (last instant inside the mid-day watch window, closes 01:00Z) mints a fresh
  permit expiring 00:59Z+10h = **10:59Z**. Union of coverage: 16:50Z→10:59Z ≈
  **18h09m**. **Gap** to STOP_PRIOR: ≈ **5h41m**.
- **WITH the cap** (`RULING_permit_daily_coverage_2026-09-25.md`, being
  implemented): a mid-day-relaunch permit is capped to expire no later than
  the day's first-boot expiry — coverage collapses back to the nominal case
  (≤02:50Z); the 5h41m worst-case gap does not arise.
- **Decision windows vs. the gap:** the four station entry windows union to
  17:00Z→01:00Z. BOTH the nominal gap (02:50Z-16:40Z) and the worst-case gap
  (10:59Z-16:40Z) fall entirely OUTSIDE that union — under either posture, no
  live entry-decision instant is denied by the gap today.

## 4. Consequences

- **(a) Accept:** zero cost today — `pm_us_crh_v4` is halted under A1(ii)
  (`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`), so no family can send
  regardless of permit coverage. Independent of the halt, any order attempted during the gap is refused at two structural chokepoints (`safety.py`'s venue-egress permit check and the kernel `BacktestOrderGuard` from `a49c7b4`), so the accepted gap is an observability gap, never an authorization gap. Future cost if a family re-arms: an
  unquantified lapse risk outside the current decision windows, undetected
  until B1 lands (deliberately unalerted before then, per Amendment B-3).
- **(a′) Move LAUNCH later:** touches a pinned, tested constant embedded in
  the STOP_PRIOR/LAUNCH/SELF_CHECK/MIDDAY_WATCH state machine
  (`trade_supervisor_core.py`) for zero benefit today; does not by itself
  bound the mid-day multi-mint hazard (a later LAUNCH still re-mints 10h on
  relaunch). **No claim is made that it shifts the capture or KILL-clock
  schedules** — Rev 1 of the completion plan made that claim and Rev 2
  struck it as unverified; this ruling does not revive it.

## 5. RULING

**(a) — accept the 02:50Z→16:40Z gap, documented here and in the runbook, and
NOT alerted until B1 (the Actor-based lapse detector) exists.** No sending
family can place an order under today's A1(ii) halt, so nothing is gained by
closing the gap now; (a′) remains available and cheap to reopen at any future
family registration; the worst-case multi-mint extension is a separate,
already-in-flight safety item (permit cumulative coverage), not a reason to
also move LAUNCH.

## 6. What would revisit this ruling

A future A1-class re-arm whose decision or exit windows extend past 01:00Z
UTC, or whose design otherwise makes the gap costly, should re-open (a′) as
part of that registration's own review. The permit-cumulative-coverage cap
landing is independent and does not itself require revisiting this ruling.

## Countersign — security-reviewer

Verdict: **ENDORSE**
Findings:
- Arithmetic (13h50m nominal gap, 5h41m worst-case gap) independently re-derived — `safety.py:172`, `trade_supervisor_core.py:33-35,864-868`, `app/trade.py:651`, `trade_supervisor.py:1352-1379`.
- Decision-window union 17:00Z→01:00Z re-derived from fixed never-DST station offsets (MIA −5, MDW −6, LAX/SFO −8) — `docs/specs/GO_LIVE_READINESS_METHODOLOGY_2026-09-06.md:21`, `R8_OPERATOR_RUNBOOK.md:139`; calendar/DST-invariant by design.
- Exit seam bounded within `[12:00,17:00)` LST per station — `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md:39`; does not extend past 01:00Z.
- A1(ii) halt currently SET (verified in `docs/evidence/AUD-02b_halt_deployment_2026-09-25.md`: payload evidence_sha256 matches the A1 ruling).
- Orders during the gap are refused at two structural chokepoints independent of alerting; the gap is observability-only (text added to §4).
- No security property is weakened; documentation-only ruling consistent with Amendment B-3.
Signature: security-reviewer, 2026-09-25
