# P4 r1 review — security-reviewer

**VERDICT: REQUEST-CHANGES.** The core design (option A, GTD, qty 1, the permit, the daily-spend ledger) is sound. The plan overstates how reliably the harm stop and slug cancel-all protect money, and it leaves several arming mechanics unspecified. It never sets or changes the operator caps (only "Do not touch the caps"), which is correct.

**Required changes**

1. **D1 does not fire at the 3rd loss in time.**
   - The producer runs once daily at 12:50Z (`deploy/systemd/breezy-maker-loss-stop.timer`).
   - A fill stays PENDING and is excluded from every count until 48h after its station-day ends (`harm_stop.py` `SETTLEMENT_PENDING_WINDOW`).
   - So the 3rd loss is seen about 2–3 days after the fill. Up to 5 bids a day keep posting meanwhile, so more than 3 losses can accrue.
   - Fix: state the real lag and size the worst case from it.
   - The "$36" worst case in Risk 1 is not derived. Replace it with a derivation: 5 bids/day × 0.80 × lag days, plus the 3 losses.

2. **Do not rely on slug-scoped cancel-all.**
   - `docs/evidence/b2/maker_positive_control_20261022T075159Z.json` records `s2_b_state_after_cancel_all = ORDER_STATE_NEW`, yet `S-2` is PASS and `SLUG_SCOPED_CANCEL_ALL` is licensed. That is the sibling order left live.
   - Risk 3 and the STOP step ("cancel all resting orders") need an explicit procedure.
   - Fix: cancel per order id, then list the venue's open orders and require zero for the family.
   - Also confirm that `set_family_halt_cli` only vetoes a running node (the veto is polled in `strategy.py` `_check_veto`) and does not itself cancel anything.

3. **Rollback is not safe as written.**
   - "Restore the drop-in" needs its `DROPIN_ALLOWLIST` row (`health_dropins.py:47`) restored too, since step 5 removes it. Otherwise the unit-health drift check flags the restored drop-in.
   - `KillMode=process` (supervisor unit, line 163) means a supervisor restart does not stop the node.
   - Rollback therefore must stop the node and confirm a DISPOSED line, not just restart the supervisor.
   - The same applies to arming: my notes say the shadow node runs all day. A supervisor restart will not load `BREEZY_SENDING_FAMILY_ID` into a surviving node, so the arming step needs an explicit node stop and relaunch.

4. **Define and test the family rename end to end.**
   - `FAMILY_ID` is hardcoded in `harm_stop_artefact.py:26` and `composition.py`, and `pm_us_no_maker_sharp_v1` is referenced in about 10 files. Among them are `deploy/systemd/breezy-maker-loss-stop.service`, `scripts/analysis/maker_loss_stop_producer.py`, the `test_family_halt_cli_fq` test, and `maker_settlement_crosscheck.py`.
   - A new `deploy/families/pm_us_no_maker_control_v1.json` manifest is needed. Its `live_orders_ruling` must name the new ruling and the file `RULING_operator_maker_control_live_<date>.md`; its `d0_climate_day` must be real.
   - The plan lists only the golden test and `HALTABLE_COMPOSITION_KINDS`.
   - Fix: add a grep-clean step so no loss-stop or halt path stays on the sharp id. A stale id would produce a harm-stop artefact the node never reads, which is the stale-deadman veto, or worse a mismatched family.

5. **The daily 5-bid cap is a real change and is not specified.**
   - `strategy.py` has no daily post counter (only `max_simultaneous=8`, `params.py:60`).
   - Also fix the counter's semantics: whether it counts posts or re-posts after a price-change cancel, and whether it resets at the UTC day.
   - Setting `max_simultaneous=5` alters the frozen rule. Also record that the control rule has no replay evidence.

6. **PASS and STOP are inconsistent with D1.**
   - D1 FAIL is T1 (L≥3) or T2 or T3, and it is counted per station-day. The tally script counts "losses".
   - Fix: make the script reuse `harm_stop.evaluate_harm_stop`, or drop it (see simplification 2). Otherwise the two can disagree on when STOP occurs.

7. **Step 4 states the S2 retirement and the C7 re-baseline without evidence.** It also says "No ruling document" while step 5 requires one. Reconcile this, and state that the pin re-baseline is its own reviewed commit.

**Not load-bearing cuts (step 6)**
- The shadow-day pass, the Δ±600 s reruns and the sequential KILL machinery are not safety-critical, given the D1 stop, the 26h `MAX_AGE_H` deadman in `loss_stop_probe.py`, and the GTD expiry.
- GTD is bounded by `gtd_expire_ns` = min(hard cancel, permit expiry, end of UTC day), `rule.py:231`. That bounds the orphan risk if the node dies, but the plan should cite it.
- The venue-fee drift probe is correctly kept.

**Simplifications**
1. Skip the `sharp_would_pick` logging in step 3. It is scope creep and it touches the order-decision path.
2. Drop the tally script and the timer wiring. D1's artefact already carries counts (`wins`, `losses`, `n`, `cum_pnl`), so a short reader or a manual check is enough.

**MEDIUM**
- Verify the ledger bound against the daily-spend ledger before arming.
- Make the first-day check explicit: confirm `resting_bind` and a GET confirm.
- The `parse_position_resolutions` replay with `unreadable == 0` should be a hard gate.

**Confidence: 78**