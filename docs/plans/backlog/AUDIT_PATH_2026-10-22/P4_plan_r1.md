# P4 plan r1 — live qty-1 maker test (2026-10-22; author trading-bot-architect)


**Goal:** Measure whether resting GTD BUY_NO bids on the frozen "control" rule win at least 38 of 40 fills and net at least +$0.02 per contract after real commission.

**Decision: use option (A), the `arm/integration` branch at `c614fb0b`. Do not build (B).**
- (B) would rebuild what (A) already has and has tested: the strategy, the resting-order exec path (B1–B7), the harm stop (D1), poll-based fill booking, boot sweep and cancel-on-stop.
- A runner outside the node would need its own order ledger, idempotency, cancel and reconcile logic, and would bypass the permit, the daily-spend ledger and the NO-SEND firewall. That is the larger and riskier build, and it breaks the Nautilus-native rule in CLAUDE.md.
- (A) needs one real code change: select the control rule.

**Is the rule configurable to "control"?** Yes, with one line.
- `src/breezy/strategy/no_ladder_maker/params.py` already defines `CONTROL_V1` (p_min 0.94, e_min 0.10, bid 0.70–0.80, abstain_unlisted True) next to `SHARP_V1`.
- `build_no_ladder_maker_strategy(params=…)` in `composition.py` takes the rule as a keyword that defaults to `SHARP_V1`.
- `tests/strategy/no_ladder_maker/test_rule_port_equivalence.py` already checks both rules against the design driver.
- The only edit is passing `params=CONTROL_V1` at the build call site. I did not locate that site; the `params=` grep over `app/trade.py` found nothing, and the dispatch is somewhere in the C2 wiring in `trade.py` or `node_plugins.py`.
- The family id (`pm_us_no_maker_sharp_v1`) and order-id tag (`SHARP`) are cosmetic. Use a new `pm_us_no_maker_control_v1` and tag `CTRL` so the books don't mix, since the harm stop is keyed on the family id.

**Inputs**
- Branch `arm/integration` in `/home/jon/breezy-arm-int`.
- B2 evidence in `docs/evidence/b2/`, which holds both `*_VERIFIED` flips.
- `parse_position_resolutions` and the venue POSITION_RESOLUTION collector.
- The D1 producer `scripts/analysis/maker_loss_stop_producer.py`.
- Gate precondition: P1 PASS and P3 PASS, both read before any step below.

**Steps**

1. **Add the one-line rule switch.** Do this on a branch off `arm/integration` (the arm-commit branch of step 5), not on `arm/integration` itself.
   - Edit the call site to pass `CONTROL_V1`.
   - Change `FAMILY_ID` and `ORDER_ID_TAG` to the control names in `harm_stop_artefact.py` and `composition.py`.
   - The existing manifest golden test and the `HALTABLE_COMPOSITION_KINDS` row need the matching name update.
   - Add a RED→GREEN focused test that the built strategy carries `CONTROL_V1`.

2. **Cap at 5 bids per day.**
   - `max_simultaneous=8` limits resting orders, not bids per day. I did not find a daily bid counter, so verify first by reading the strategy.
   - If none exists, add a small daily post counter in `NoLadderMakerStrategy._decide`, with a RED test, and refuse the 6th post. Set `max_simultaneous=5` in `CONTROL_V1`. This changes the frozen rule's constants, so do it before the first order and record it in the commit message.
   - The operator caps stay untouched. The `DailySpendLedger` remains the dollar backstop.

3. **Log sharp's picks as a subset.**
   - In the same strategy, evaluate `SHARP_V1` on the same book state per decision and write `sharp_would_pick: bool` to the decision log line. Use the existing `selector.build_selector`; it is read-only and needs no second order path.
   - The sharp results are then a post-hoc filter of control fills, with no extra orders.

4. **Merge `arm/integration` into feat now.**
   - The hold on the merge was the S2 programme's byte-pins on the exec files. The operator replaced the backlog, so S2 no longer gates anything.
   - Re-baseline the C7 pin JSON in one commit that lands before the merge. The pin test stays in place and green at every commit; only the baseline bytes change.
   - Put "S2 verdict retired, no S2 re-run" in the commit message and one PROGRESS line. No ruling document.
   - After the merge, run the full gate `scripts/ci/run_tests_no_egress.sh`.
     - Read the EXIT code before any push.
     - The only red allowed is the by-design C7 pin, which the re-baseline turns green.
   - Merge preview rule R9 applies: if any pinned file moved on feat, re-run the B-chain focused gates on the preview.

5. **Pre-ARM steps to keep (money-safety or gate measurement only).**
   - Set the real `d0_climate_day` in the manifest. The boot refuses on the placeholder `2026-10-28`.
   - Allowlist row in `live_orders_gate.py` plus the widened `test_fq_live_orders_gate.py`.
   - Replay the venue activities through `parse_position_resolutions` and require `unreadable == 0`. This is how settlement and P&L are booked against the gates.
   - Install `breezy-maker-loss-stop.{service,timer}` (`mkdir` the derived dir first). Confirm one fresh harm-stop PASS. Check that the node refuses to trade when the stop is stale, which is the existing deadman.
   - ARM commit:
     - Move the `fq-v1-halt-orders-off.conf` drop-in to a backup outside `.d/`.
     - Remove its `DROPIN_ALLOWLIST` row and update `test_unit_health_dropins.py`.
     - Set `BREEZY_SENDING_FAMILY_ID=pm_us_no_maker_control_v1` in `deploy/systemd/breezy-trade-supervisor.service`.
     - `live_orders_ruling`: the live-orders gate requires a named ruling sha, so write one short file `deploy/families/rulings/RULING_operator_maker_control_live_<date>.md`.
       - It carries only this plan's gates and the pre-declared harm stop, and its sha is pinned in the allowlist row.
       - This is the mechanical gate input, not extra governance.
     - Do not touch the caps.
   - Then daemon-reload and a supervisor restart, in the 01:00–16:40Z window. A supervisor restart is required for the change to load.
   - Check at 16:50Z:
     - the permit line in the node log;
     - `enabled=True reason=ok`;
     - a clean boot sweep;
     - the first `resting_bind` with a GET confirm.
   - Rollback: restore the drop-in, restart the supervisor, run `set_family_halt_cli`.

6. **Cut these pre-ARM steps:**
   - the separate shadow-day pass (the 17 shadow-only verifications);
   - the PMR and security re-review ceremony for a sharp ruling;
   - the Δ=±600 s reruns;
   - the Sequential KILL machinery.

   Keep the D1 harm stop and the venue-fee drift probe, since both are already built.

7. **Daily check script (one-off, cron or manual).** Add `scripts/analysis/maker_control_tally.py`, about 60 lines, reading the fills and POSITION_RESOLUTION rows for this family. It prints:
   - fills;
   - wins;
   - losses;
   - net per contract after actual commission (the commission comes from the activity, not from θ);
   - days elapsed;
   - a one-word verdict.

   The harm stop (D1) halts the family at the 3rd settled loss, and the script's STOP exit mirrors it. Wire the script as a daily line in the existing truth-fetch/loss-stop timer chain rather than a new unit.

**PASS / FAIL / STOP (numeric; fixed before any fill)**
- **PASS:** at least 38 of 40 fills win AND net ≥ +$0.02 per contract after actual commission.
- **STOP, any of:**
  - 3 losses (D1 halts automatically; the tally script confirms);
  - fewer than 10 fills at day 21;
  - 45 days elapsed.
- On a STOP, run `set_family_halt_cli`, cancel all resting orders, and restore the drop-in.
- A fill is a resting bid that executed. Count settled outcomes only; an unsettled position holds the verdict.

**Effort and wall-clock**
- Code: about 1 day, tdd-guide.
  - Rule switch and names.
  - Daily-bid counter.
  - Sharp-subset log line.
  - Tally script.
- Gates and merge: about half a day, one full gate run.
- Live window: 21 to 45 days.

**Risks (max 3)**
1. **The control rule has no replay evidence of its own live edge.** Only the sharp arm was nominated. Worst case is about $36, qty 1, at most 5 bids/day. The 3-loss STOP bounds the loss.
2. **Maker fills may be adverse-selection sweeps, and the sim has no placement latency.** The test measures this directly; P3 and P1 must have passed first.
3. **Orphaned or ambiguous resting orders.** Mitigated by the GTD backstop, the boot sweep, per-order cancels and slug-scoped cancel-all (already tested). Never use an empty-slug cancel-all.

**What we deliberately do NOT do**
- No (B) runner, no new harness or ledger.
- No change to the Nautilus foundation.
- No setting or changing of the operator caps.
- No new governance documents beyond the single live-orders ruling file.
- No weakening or deletion of any pin, safety or NO-SEND test.
