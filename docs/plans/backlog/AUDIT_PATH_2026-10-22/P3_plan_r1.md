# P3 plan r1 — GTD horizon probe (2026-10-22; author planner)


**Goal:** find out whether Polymarket.us keeps a $0.01 GTD order resting for several hours and expires it on time. FAIL means a maker design that rests for hours is impossible on this venue.

## Inputs (each checked against the files)
- **The script to reuse:** `/home/jon/breezy-arm-b2/scripts/venue/polymarket_us_maker_positive_control.py` and `_maker_control_core.py` (branch arm/b2-control). It sends no client-order-id, because the venue body has none: `RESTING_ORDER_BODY_KEYS` holds nine keys, and SKILL.md L333 records the gap. The order's identity is therefore our own tuple (slug, BUY NO, qty 1, 0.01, the exact `goodTillTime` second we send) plus the venue id from the create response. A preflight that requires zero open orders makes that tuple unique.
- **B2 evidence:** `/home/jon/breezy-arm-b2/docs/evidence/b2/maker_positive_control_20261022T075159Z.json` is a full PASS. The first GET after each create returned 404 and the second (about 1 s later) returned 200, so propagation is under 2 s. Slug cancel-all leaving B (the order on the second slug, Y) live was the S-2 PASS, not a defect: cancel-all is scoped to the slug, not the event. This probe therefore never uses cancel-all and cancels only by id.
- **Maximum GTD horizon:** none is documented. The `docs_snapshots/` insert-order, preview and get-order pages, and SKILL.md L335/L339, give `goodTillTime` only as date-time. It is unknown, so the probe measures it (order A below).
- **What the live rule actually sends:** `rule.gtd_expire_ns` takes the minimum of D 09:00 LST, the permit expiry (`PERMIT_TTL_NS` = 10 h) and UTC midnight. At the 16:50Z boot that sends GTDs about 7.2 h ahead, which is longer than any simulated rest. So the probe has to test acceptance of a long GTD (order A) as well as one rest-and-expire (order B).
- **Simulated rest durations:** `/home/jon/.local/share/breezy/derived/replay/design/maker_nobid_sharp/{sharp,sharp_cap84}/episodes.jsonl` has 3,578 episodes in sharp. I could not compute durations here, so Step 0 measures them; the 3.4 h max and about 1,100 s median are not yet confirmed.
- **Node:** the R13 precondition refuses to start if a node exists. The node's boot check (`StartupPositionEvidence`) arms only when there are no open orders, and logs ERROR `startup_open_orders_present` otherwise.

## Steps
0. **Rest horizon H** (read-only, about 5 min). Run `/home/jon/breezy/.venv/bin/python -I -c '…'` on both `episodes.jsonl` files. For each episode with `refused_reason` null, compute `rest_s = ((filled_ns_base or end_ns) − t0_ns)/1e9` and print p50, p95 and max per arm. **Rule:** H = max(4 h, max rounded up to the next 30 min + 30 min), capped at 6 h. If the 3.4 h figure holds, H = 14,400 s. Paste the printout into the evidence file's `details`.
1. **Code change** (in the arm/b2-control worktree; nothing under src/). Use a flag rather than a new script: a new script that sends orders would need about 5 new firewall exemption rows, while a flag only needs 2 sha re-digests.
   - `_maker_control_core.py`:
     - Add `HORIZON_GTD_CEILING_SECS = 36_000` (the permit TTL).
     - Add a `ceiling_secs=GTD_CEILING_SECS` keyword to `assert_gtd_within_ceiling` and `is_own_probe_shape`.
     - Add `--horizon-secs` to `parse_args` (int in [3600, 21600], mutually exclusive with `--select-only`).
     - Add `RunState.horizon_secs` and a horizon branch in `document()` (`mode="horizon"`, verdicts `P3` and `P3_A_ECHO`, every licence False).
     - `GTD_CEILING_SECS == 600` and every `MAX_*` constant stay exactly as they are.
   - `polymarket_us_maker_positive_control.py`:
     - Add a `gtd_ceiling_secs` attribute on `ControlSession`, used by `_build_resting_body`, `rest` and `_cleanup_by_listing`.
     - Add a `Budget(max_creates=2, max_cancels=2, max_gets=60, max_aux_gets=20)` instance for horizon mode only.
     - Add `_horizon_sequence`, split into `_choose_horizon_slug`, `_echo_probe_A` and `_watch_B`, each under 50 lines:
       - **Slug:** skip the activities read. Pick one slug from the existing ranking whose event date is after today (UTC), whose `market_exclusion(market, now_ns=now+H)` is None, and whose quote reads OK.
       - **A (echo only):** rest with GTD = 36,000 s. Sleep 1 s, then confirm up to 10 polls × 1 s, treating 404 as "not yet". Record the echo minus the sent time, cancel by id, and confirm CANCELED.
       - **B:** rest with GTD = H and confirm the same way (NEW, GTD, echo within 1 s).
       - **Heartbeat** every 900 s: GET B, plus `probe_production_node()` (read-only), plus one stderr line `P3 hb k state=…` for the stall watch.
       - **Expiry:** GET at G−30 s, then GET at G+60 s. If B still reads NEW there, cancel it by id.
       - Finish with the existing `_final_clean_check`. On any exception, run the existing `_cleanup` (cancel by id, then a listing match on the exact tuple). Evidence goes to the same directory with stamp `horizon_<UTC>`.
2. **Tests** in a new file, `/home/jon/breezy-arm-b2/tests/unit/test_polymarket_us_maker_positive_control_horizon.py`, reusing `b2_control_fakes` with a fake clock. Cases:
   - PASS
   - early EXPIRED → FAIL_EARLY
   - NEW at G+60 → FAIL_LATE, then cancel by id
   - echo off by more than 1 s → FAIL_CLAMPED, then cancel
   - 4xx on create → FAIL_REJECTED
   - a node appearing mid-run → INVALID
   - GTD above 36,000 s refused before signing
   - with no flag, the S-1/S-2/S-6 path is unchanged
3. **Guard pins:** re-digest the control script in `tests/contract/test_us_source_ingest_egress_guard.py` (M6 baseline) and `tests/unit/test_polymarket_us_cancel_transport.py`, keeping a "Prior digest" comment. The call-site sets (`rest`, `retract_order`) are unchanged, so no exemption rows are added. Run the focused tests, the existing B2 test files, those two guards, `test_polymarket_us_readonly_guard.py`, `test_polymarket_us_write_transport.py`, `test_resting_path_firewall_delta.py`, and `lint-imports` from inside the worktree, with `PYTHONPATH=/home/jon/breezy-arm-b2/src` and `--basetemp` under `~/.cache`. The full gate is not needed to run the probe (no src/ change); it is needed before arm/b2-control merges. Review: python-reviewer and security-reviewer.
4. **Window:** start between 10:00Z and 12:00Z on day X. D+1 markets list at D−1 09:45Z, and the run must end before 16:40Z. SIGTERM the node and wait for DISPOSED, as B2 did. Leave it down; the supervisor's 16:50Z boot brings it back, and by then the account check has shown no open orders.
5. **Dry run:** `--select-only` first.
6. **Live run:**
   `systemd-run --user --unit=breezy-p3-gtd-probe -p MemoryMax=1G -p RuntimeMaxSec=$((H+3600)) -p WorkingDirectory=/home/jon/breezy-arm-b2 -E PYTHONPATH=/home/jon/breezy-arm-b2/src /home/jon/breezy/.venv/bin/python scripts/venue/polymarket_us_maker_positive_control.py --run-date X --horizon-secs H`
   - Watch with `journalctl --user -u breezy-p3-gtd-probe`. It counts as stalled if no `hb` line appears for more than 20 min, or if ActiveState leaves `active`.
   - If RuntimeMaxSec fires, the SIGTERM handler cancels by id.

## PASS / FAIL / STOP (fixed before any result is read)
G is the sent `goodTillTime` (whole seconds); T_c is the create time.
- **PASS** requires all of the following:
  - B's create returns 200 with a valid id.
  - Within 10 s, B reads NEW and GTD with |echo − G| ≤ 1 s.
  - Every heartbeat, and the G−30 s read, shows NEW. The G−30 s read may be retried twice at 5 s.
  - The read issued in [G+55 s, G+65 s] shows `ORDER_STATE_EXPIRED`.
  - Nothing filled, the final open-orders list is empty, and every own order is terminal.

  The resolution is therefore that expiry falls inside [G−30 s, G+60 s].
- **FAIL** (binding for the audit gate):
  - F1 REJECTED: B's create returns 4xx.
  - F2 CLAMPED: the echo differs from G by more than 1 s. Record (echo − T_c) as the venue's horizon.
  - F3 EARLY: any read up to and including G−30 s shows EXPIRED, CANCELED or REJECTED. Record [last NEW, first terminal] relative to T_c.
  - F4 LATE: B still reads NEW at G+60 s.
- **INVALID** (not a verdict): any of these.
  - A precondition refuses.
  - No D+1 slug passes the guards.
  - Any fill.
  - A create is left in doubt.
  - The G−30 or G+60 read is unreadable after retries.
  - A node appears during the run.
  - On F3, one public market read shows the market is no longer OPEN.

  Rerun once on a later day. A second INVALID means STOP and report UNTESTABLE.
- **Secondary readout, not part of the gate:** `P3_A_ECHO` ∈ {OK, CLAMPED(h), REJECTED}. Anything other than OK means the ARM rule's `gtd_expire_ns` must be capped at the largest proven horizon before arming. That is a separate item.
- **STOP:** after one verdict. No horizon bisection and no retry after a FAIL.

## Authorization and money at risk
- **Authorization:** the operator adopted the audit's 5-item path as the backlog on 2026-10-22 (`AUDIT_independent_2026-10-22.md` L46, item 3), and B2 ran a probe of the same shape that day. This plan is the named exception with a capital ceiling that `docs/core/AGENT_ARCHITECTURE.md` L57/L168 requires.
- **What it touches:** neither operator cap, nor enablement, the permit, `allow_short` or the NO-SEND firewall rows.
- **Exposure:** two qty-1 BUY NO orders at $0.01, so $0.02 notional. Code caps it at 2 creates and 2 cancels. Worst case is both fill and settle against us: a loss of at most $0.04 including fees (fee ≈ 0.0695·0.01·0.99 ≈ $0.0007 per fill, at most $0.01 after rounding).

## Effort and wall-clock
About 2–3 h of agent work (about 120 lines of script plus tests) and 1 review round. Run time is H + 10 min (≈4 h 10 m), done the same day. Node downtime is about 5–7 h of a shadow node that the audit says yields no evidence.

## Risks
1. **A supervisor relaunch or hand launch during the window.** Mitigation: R13 at start, a node probe at every heartbeat (any node makes the run INVALID), and an end time before 16:40Z.
2. **A venue halt or resolution cancels B for reasons unrelated to the horizon** (false F3). Mitigation: a D+1 middle rung, plus the market-status read on F3, which makes the run INVALID.
3. **Re-digesting the guard pins needs re-review.** That is intended. `GTD_CEILING_SECS == 600` and the call-site sets stay pinned and green.

## What we deliberately do NOT do
- No new module, harness, unit file, timer, PREREG or ruling, and no src/ change.
- No cancel-all.
- No change to or relaxation of the R13 precondition, and no node coexistence. Coexistence is probably harmless with orders off, but the boot open-order check and R13 both argue against it, and the downtime costs about nothing.
- No 7–10 h rest-and-wait: order A covers acceptance of long GTDs.
- No flip of `GTD_EXPIRY_VERIFIED` (B2 already licensed it).
- No check of the maker fee sign.
- No test of whether a dropped private-WS session cancels resting orders (`UNSOLICITED_CXL_REASON_CONNECTION_LOSS`). The probe is REST only, so that question stays open for audit item 4.