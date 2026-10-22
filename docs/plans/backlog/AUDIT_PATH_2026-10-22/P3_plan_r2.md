# P3 plan r2 — GTD horizon probe, one order, 4 h (2026-10-22; supersedes r1 per reviews/P3_r1_security.md + reviews/P3_r1_grok.md)


**Goal:** find out whether one $0.01 GTD order stays NEW for 4 h on Polymarket.us and expires on time. A PASS licenses only the 4 h actually waited.

## Inputs
- **Script:** `/home/jon/breezy-arm-b2/scripts/venue/polymarket_us_maker_positive_control.py` and `_maker_control_core.py` (branch arm/b2-control).
- **Order identity:** the venue has no client-order-id (the resting body is 9 keys). Identity is the tuple (slug, BUY NO, qty 1, 0.01, exact G), plus the venue id from the create response. The preflight requires zero open orders, which makes the tuple unique.
- **B2 evidence:** `docs/evidence/b2/maker_positive_control_20261022T075159Z.json` (PASS). The first GET after create may return 404. Slug cancel-all is scoped to the slug, so this probe never uses cancel-all.
- **Horizon:** H = 14,400 s, fixed. It covers the simulated rests (≤ 3.4 h). No maximum GTD horizon is documented.

## Steps
1. **Code change** (scripts/ only, nothing under src/):
   - **Flag and constants:** add a boolean `--horizon` flag and `HORIZON_GTD_SECS = 14_400`. The unflagged 600 s path, `GTD_CEILING_SECS == 600` and every `MAX_*` pin keep exactly their current behaviour.
   - **Ceiling:** `assert_gtd_within_ceiling` and `ControlSession` take `ceiling_secs`, which is `GTD_CEILING_SECS` unless `--horizon` is set.
   - **Listing cleanup:** `is_own_probe_shape` gets an `exact_gtd_ns` parameter. In horizon mode, `_cleanup_by_listing` passes G, so only the exact G matches, never a ceiling-width window.
   - **Slug rule:** pick one slug whose event date is after today (UTC), where `market_exclusion(market, now_ns=now+H)` is None, and whose quote reads OK. `--select-only --horizon` applies the same rule.
   - **Sequence:** preflight (R13 node check, zero open orders), then rest B. Confirm by sleeping 1 s, then up to 10 polls × 1 s with 404 tolerated, and require |echo − G| ≤ 1 s. After that: one GET at T_c + H/2, one GET at G−30 s (2 retries at 5 s), one GET at G+60 s. If B still reads NEW at G+60 s, cancel it by id and confirm CANCELED. Then run the existing `_final_clean_check`.
   - **Cancel reasons:** record verbatim any cancel-reason enum on the order GET (for example `UNSOLICITED_CXL_REASON_*`). SKILL.md L339 notes this field may be absent on Order objects.
   - **Budget:** `Budget(max_creates=1, max_cancels=3)`; GET limits stay at their defaults. Horizon mode skips the activities read.
   - **Failure handling:** SIGTERM or any exception runs the existing `_cleanup`, which cancels by id. In horizon mode the `left_to_gtd` path never polls. It reports `LEFT_ORDER_NOT_LAPSED` and writes `order <id> may rest until <G>; cancel by hand` to stderr.
   - **Evidence:** `document()` gets one branch, `passed = verdicts["P3"] == "PASS"` plus the existing clean, no-fill and no-leftover terms. Every licence is False. The stamp is `horizon_<UTC>`.
2. **Four tests,** in a new file `tests/unit/test_polymarket_us_maker_positive_control_horizon.py` using `b2_control_fakes`:
   - (a) without the flag, a 601 s GTD is still refused (the 600 s pin);
   - (b) in horizon mode, a GTD of H+1 s is refused before signing;
   - (c) PASS;
   - (d) LATE leads to cancel by id.
3. **Guard re-digests,** each keeping a `# Prior digest: c73801fa…` comment:
   - `test_m6_b2_control_row_is_exempt_only_while_its_sha_matches`: the `M6_PREEXISTING_BASELINE` entry in `tests/contract/test_us_source_ingest_egress_guard.py`;
   - `test_b2_control_exemption_is_sha_pinned_and_load_bearing`: `_B2_CONTROL_SHA256` in `tests/unit/test_polymarket_us_cancel_transport.py`.

   The call-site pins in `test_polymarket_us_readonly_guard.py`, `test_polymarket_us_write_transport.py` and `test_resting_path_firewall_delta.py` must pass unchanged. That is the machine check that no write site was added. Run with `PYTHONPATH=/home/jon/breezy-arm-b2/src` and `lint-imports` from inside the worktree. One security-reviewer pass on the diff. The full gate runs only when arm/b2-control merges.
4. **Window:**
   - The start must be ≥ 10:00Z (D+1 markets list at 09:45Z) and start + H + 15 min < 16:40Z, so the latest start is 12:25Z.
   - SIGTERM the node and wait for DISPOSED, as B2 did.
   - Nothing relaunches inside this window. The supervisor stops at 16:40Z, launches at 16:50Z, relaunches only until 17:00Z, and its midday watch runs only 16:50Z→01:00Z (`trade_supervisor_core.py:37-40,668-689`).
5. **Dry run:** `--select-only --horizon`.
6. **Live run:**
   `systemd-run --user --unit=breezy-p3-gtd-probe -p MemoryMax=1G -p RuntimeMaxSec=18000 -p WorkingDirectory=/home/jon/breezy-arm-b2 -E PYTHONPATH=/home/jon/breezy-arm-b2/src /home/jon/breezy/.venv/bin/python scripts/venue/polymarket_us_maker_positive_control.py --run-date <today> --horizon`
   - Watch it with `journalctl --user -u breezy-p3-gtd-probe` and the unit's ActiveState.

## PASS / FAIL / INVALID (fixed before any result is read)
G is the sent `goodTillTime`; T_c is the create time.
- **PASS** requires all of: echo within 1 s of G; NEW at the confirm read, the mid-rest read and the G−30 s read; `ORDER_STATE_EXPIRED` at the read issued in [G+55 s, G+65 s]; no fill; the final open-orders list empty.
- **FAIL** (binding: multi-hour resting is not supported):
  - CLAMPED: the echo differs from G by more than 1 s. Record (echo − T_c).
  - EARLY: any read up to and including G−30 s shows a terminal state. Record the bracket and any cancel reason verbatim.
  - LATE: B still reads NEW at G+60 s.
- **INVALID** (not a verdict): any of these.
  - A precondition refuses.
  - No eligible slug.
  - Any fill.
  - The create is left in doubt.
  - The create returns 4xx, unless the response explicitly rejects the GTD or expiry; then it is FAIL.
  - The G−30 or G+60 read is unreadable after retries.
  - The budget is exhausted.
  - EARLY-CANCELED while the public market read shows the market is no longer OPEN.

  INVALID means rerun once on a later day. A second INVALID means STOP and report UNTESTABLE. Every verdict ends the probe.

## Safety and authorization
- **Authorization:** this plan is its own named per-dispatch exception (P3 GTD probe, 1 order, ceiling $0.02). It sits under audit backlog item 3, which the operator adopted on 2026-10-22. It departs from the audit's 2 h on purpose: H = 4 h to cover the simulated rests. The run report carries a one-line heads-up.
- **Money at risk:** one qty-1 BUY NO at $0.01. The fee on a 0.01 fill banker-rounds to $0.00 (`fees.py:593-605`), so the worst-case loss is $0.01.
- **Untouched:** both operator caps, enablement, the permit, `allow_short` and the NO-SEND rows.
- **If the process is hard-killed** (SIGKILL, OOM or power loss), the backstop is the GTD itself (at most 4 h). After that, the 16:50Z boot's open-order check and the next run's preflight would show any order that survived.

## Effort and wall-clock
About 1.5 h of code and tests plus one review. The run itself takes about 4 h 05 m, the same day.

## Risks
1. **A venue halt or sweep could look like EARLY.** Mitigation: a D+1 middle rung, the market-status read that makes it INVALID, and the cancel reason recorded verbatim.
2. **A cancel fails and the order is left resting.** Mitigation: the budget has 3 cancels, failures get a stderr warning and `LEFT_ORDER_NOT_LAPSED`, and the GTD lapses within 4 h at most.
3. **The re-digests need review.** That is intended; the call-site pins stay green.

## Deliberately not done
- No order A, no heartbeat and no per-beat node probe.
- No horizon formula or bisection, and no cancel-all.
- No new module, unit, PREREG or ruling, and no src/ change.
- No relaxation of R13.
- No websocket leg. A dropped private-WS session cancelling resting orders is P4's question.
- No `GTD_EXPIRY_VERIFIED` flip.
- No check of whether the venue accepts the live rule's roughly 7.2 h GTD requests. This PASS licenses 4 h only.
---

## r2.1 coordinator amendments (adopting `reviews/P3_r2_security.md` + `reviews/P3_r2_grok.md`, both APPROVE-WITH-CHANGES) — STATUS: READY

1. **Cleanup on the in-doubt path.**
   - Persist `body["goodTillTime"]` **before** `post_order` (`positive_control.py:526-531`). `sent_gtd_ns` is stored only after `rest()` returns (`:665`).
   - In horizon mode, `is_own_probe_shape` matches that stored G within `GTD_ECHO_TOLERANCE_NS` (1 s). It must not use a recomputed now+H, and it must not use the 660 s window (`_maker_control_core.py:1182-1200`).
   - `_cleanup_by_listing` runs only on `create_in_doubt` (`:969`).
   - Also lift the second 600 s refuse in `_build_resting_body` (`:497-498`) for horizon mode only. The unflagged path keeps both refuses.
2. **Supervisor wording.**
   - The node stops at 16:40Z and launches at 16:50Z, and boot relaunch runs only until 17:00Z (`trade_supervisor_core.py:37-40`, `decide_relaunch` `:676-682`).
   - The midday watch opens at 17:10Z (`:50`, `:1243-1253`) and closes at 01:00Z the next day (`:1205-1209`).
   - The probe window is empty of relaunches. The latest start is **12:24Z**, to satisfy the strict `<` 16:40Z.
3. **Money ceiling.** The cap is the fill loss of one qty-1 contract at $0.01, i.e. $0.01, plus any fee. It does not depend on banker's rounding.
4. **"Explicitly rejects the GTD".** Pin it before the run to a named venue error code or message substring (from `docs/evidence/venue/polymarket_us/docs_snapshots/` or SKILL.md). Any other 4xx is INVALID.
