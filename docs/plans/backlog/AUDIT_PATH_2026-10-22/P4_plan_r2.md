# P4 plan r2 — live qty-1 maker test, sharp as built (2026-10-22; author trading-bot-architect; supersedes r1 per reviews/P4_r1_security.md + reviews/P4P5_r1_pmr.md)


**Goal:** Test whether the sharp rule's resting GTD BUY_NO bids win more often than breakeven, live, at qty 1, using the already-built `arm/integration` branch (`c614fb0b`, `/home/jon/breezy-arm-int`).

**Decision.**
- Use option (A) and run SHARP unchanged, per D1.
- Control is dropped. At about 8 fills in 13 days it would need about 65 days to reach 40 fills, and its bid range cannot overlap sharp's.
- No rename, no new family, no 5-bid counter (the existing `max_simultaneous=8` stays), no subset logging, no tally script.
- Live fills are out-of-sample even though the sharp selection was in-sample.
- The tally is the D1 harm-stop artefact (`wins, losses, n, cum_pnl`), read by hand daily.
- Option (B) is not built. It would duplicate the strategy, the resting exec path and the harm stop, and sit outside Nautilus.

**Inputs**
- P1 PASS and P3 PASS, read before any step below.
- The D1 artefact and `parse_position_resolutions`.
- The in-sample sharp positions, for the breakeven calculation.

**Cost and breakeven (frozen before the first order)**
- Cost per fill is the D1 treatment: max(venue fee, θ=0.0695), rounded to the cent, floor $0.01. At qty 1 that is a flat $0.01.
- This cost is authoritative. No rebate credit counts toward PASS. Report net per contract with and without the rebate.
- Breakeven win rate = mean bid + $0.01 over the in-sample sharp positions, about 0.875.
- Compute it once and write the exact number in the ARM commit message.

**Steps**

1. **S2 retirement / C7 re-baseline, as its own small reviewed commit.**
   - The commit message states the S2 verdict is retired and no S2 re-run follows.
   - The C7 pin test stays; only the baseline bytes change.
   - It lands before the merge (pin green at every commit), with no ruling document.

2. **Merge `arm/integration` to feat.**
   - Run the full gate `scripts/ci/run_tests_no_egress.sh` in the primary tree.
   - Read the EXIT code before any push.
   - The only red allowed beforehand is the by-design C7 pin, which step 1 turns green.

3. **Pre-ARM list from `docs/core/archive/PROGRESS_2026-10-22_pre-audit.md` (ARM section): keep or cut.**

   | Item | Decision | Why |
   |---|---|---|
   | Manifest real `d0_climate_day` (replaces the `2026-10-28` placeholder) | KEEP | Boot refuses the placeholder. |
   | Replay of valued activities through `parse_position_resolutions` with `unreadable == 0` | KEEP, hard gate | Settlement booking is how the gate is measured. No ARM without it. |
   | Install `breezy-maker-loss-stop.{service,timer}` (mkdir the derived dir first) | KEEP | The harm stop. |
   | Fresh harm-stop PASS | KEEP | Stale blocks entries. |
   | Supervisor restart | KEEP, plus step 6 | See step 6. |
   | Shadow day | CUT | Orders-off produces no evidence. Replaced by first-live-day watching in step 7. |
   | A0′ S2-retirement ruling | CUT | Replaced by the commit message in step 1. |
   | Sharp ruling `RULING_MAKER_sharp_v1_live_small_2026-10-21` | KEEP as exactly one file | The live-orders gate mechanically requires a named ruling sha. It is the only reason it exists. |
   | Allowlist row | KEEP | Needed to enable orders. |
   | Drop-in removal | KEEP | Needed to enable orders. |
   | `BREEZY_SENDING_FAMILY_ID` | KEEP | Selects the family. |

4. **The ruling file.** It holds only the gate below and the harm-stop rule. Take its sha256 and pin it in the allowlist row. Widen `test_fq_live_orders_gate.py` by one row. Do not touch the caps.

5. **Exposure ceiling, derived from the real harm-stop lag.**
   - D1 runs daily at 12:50Z and uses a 48 h PENDING window, so a 3rd loss is seen about 2–3 days after it happens.
   - Ceiling = resting orders × bid × lag days ≈ 8 × $0.89 × 3 ≈ $21 of cost basis, and a lost position loses that basis.
   - At the measured 0.7 fills/day the realistic exposure is about $2.
   - Compare the per-day figure (8 × $0.89 = $7.12) against the daily-spend ledger in read-only form.
   - If the ledger refuses an order, that only lowers fills. Never set or change a cap.
   - Orphan bound: every rest carries a GTD expiry from `gtd_expire_ns` (`rule.py:231`), so an orphaned order dies on its own by the permit end or UTC midnight.

6. **Arming needs an explicit node stop and relaunch.**
   - Edit `deploy/systemd/breezy-trade-supervisor.service` with `BREEZY_SENDING_FAMILY_ID` for the sharp family and remove the `DROPIN_ALLOWLIST` row. Move the `fq-v1-halt-orders-off.conf` drop-in to a dated backup outside `.d/`.
   - Run the full gate on the merge preview, read EXIT, then in the 01:00–16:40Z window run daemon-reload and restart the supervisor.
   - The supervisor restart alone does not reload the node. `KillMode=process` leaves the old node running without the new environment.
   - Stop the node, confirm the DISPOSED line in the log, then relaunch with the same `systemd-run --user` mirror of `spawn()`.
   - At 16:50Z check the permit line, then `enabled=True reason=ok`, a clean sweep, and the first `resting_bind` with a GET confirm.

7. **First live day.**
   - Watch it by hand. Check that the D1 artefact updates and that GETs show no foreign order on our slugs.
   - Then read the artefact once per day.

**PASS / FAIL / STOP (all fixed before the first order)**

- **Unit.** The unit is the station-day, to handle clustering. A station-day is a LOSS if any fill on it loses, otherwise a WIN. Fills on the same station-day are one trial, which is conservative because they share a weather outcome.
- **Test.** One-sided binomial against p0 = 0.875. P(PASS | p = 0.875) = 0.0449 ≤ 0.05.
- **PASS.** At least 37 station-days complete with at most 1 loss, and net per contract with the flat $0.01 cost is above zero. Report net per contract with and without the rebate.
- **Early FAIL.** The 2nd loss makes PASS unreachable, so FAIL and halt at once.
- **Harm bound.** D1's 3rd-loss halt stays, labelled as a loss bound only. It is not evidence of no edge. With 2 losses already a FAIL it is redundant here, but it halts automatically without anyone reading.
- **Horizon.** At about 0.7 station-days/day, 37 take about 53 days. The hard stop is day 75.
- **STOP.** Fewer than 8 station-days by day 21, or day 75 reached with PASS not reached.
- **Alternatives.** 0 losses in 23 has power 0.31; ≤2 losses in 49 has power 0.55 but needs about 70 days. I take ≤1 in 37.
- **Power, stated honestly.**
  - P(PASS | true p = 0.95) = 0.44.
  - P(PASS | p = 0.92) = 0.19.
  - P(PASS | p = 0.875) = 0.045.
  - A FAIL or STOP therefore does not show the edge is absent. A PASS at the 5% level is a real signal.
  - The coordinator's example of "≤1 loss in 36" gives 0.0503 > 0.05, so I use 37.

**Stop / rollback procedure**
1. Cancel per order id, not by empty-slug cancel-all.
2. List the venue's open orders and require zero on our slugs.
3. `set_family_halt_cli` is a veto, not a cancel; use it additionally, never instead.
4. Restore the drop-in AND its `DROPIN_ALLOWLIST` row, together with its test.
5. Stop the node and confirm the DISPOSED line.

**Effort and wall-clock**
- About 1 day for steps 1–6, with one full gate run before the merge push and another on the arm commit.
- About 53 days live, 75 at most.

**Risks (max 3)**
1. Sharp was picked in-sample from at least 6 arms (17/17 with a 95% lower bound of 0.839 below breakeven). Low power means an inconclusive result is the likely outcome.
2. The maker rebate sign is unproven, so no rebate counts toward PASS.
3. Orphaned or ambiguous rests. The GTD backstop, boot sweep and per-order cancel (already tested) contain them.

**What we deliberately do NOT do**
- No control arm, rename, new manifest, bid counter or tally script.
- No (B) runner.
- No change to the caps, the Nautilus foundation, or any safety, pin or NO-SEND test.
- No shadow day and no extra governance documents.

---

## r2.1 coordinator amendments (adopting the required changes of `reviews/P4_r2_security.md` and `reviews/P4P5_r2_pmr.md`; both APPROVE-WITH-CHANGES) — STATUS: READY

1. **Manifest.** Add `live_orders_ruling` and the real `d0_climate_day` to `deploy/families/pm_us_no_maker_sharp_v1.json`. Without `live_orders_ruling`, `live_orders_authorized` returns `no_ruling`. Update the family-manifest golden and marker tests for the new bytes.
2. **Ruling file.** Exactly one, at `deploy/families/rulings/RULING_MAKER_sharp_v1_live_small_<date>.md`. Its sha256 is pinned in the allowlist row.
3. **Guard tests that flip by design.** Update, never delete or weaken:
   - `tests/unit/test_no_ladder_maker_wiring.py:69` ("live sending is off");
   - `tests/unit/test_unit_health_dropins.py:117` (single-row unpack).
   Each must assert the new intended state, and the reverse assertion must come back on rollback.
4. **Null pinned exactly.** p0 = mean stress-fill bid 0.8647 + $0.01 = **0.8747**, from `maker_nobid_sharp/sharp/positions.csv`, 17 fills. Write it in the ARM commit message.
5. **One evaluation.** PASS/FAIL is evaluated once, at exactly the first 37 *settled* station-days. An unsettled fill holds its station-day out of the count. PASS = at most 1 loss. "Net > 0" is a safety clause, not the inference. No re-test at n = 38, 39, …
6. **The 2nd-loss FAIL is a manual daily read.** The coordinator reads the D1 artefact after the 12:50Z producer run. On a 2nd settled loss: `set_family_halt_cli`, then the stop/rollback procedure. Same lag as D1, so the exposure bound stays ≈ $21. D1's automatic 3rd-loss halt remains the backstop.
7. **Rate check.** At day 21, fewer than 8 station-days or a rate below 0.5/day ⇒ STOP (inconclusive, not FAIL). The expected rate is 0.62–0.70/day and is in-sample, so it may be optimistic.
8. **Harm-stop artefact.** A HOLD writes no file, so confirm the artefact exists after the first producer run before arming.
9. **Cap live GTDs at the P3-licensed horizon** (P3 r2 verifiers, both, option (a): `reviews/P3_r2_security.md`, `reviews/P3_r2_grok.md`).
   - Add `now_ns + P3_LICENSED_GTD_NS` (14,400 s, a named constant whose comment cites the P3 evidence) to the `min()` in `gtd_expire_ns` (`no_ladder_maker/rule.py:231-238`). Add one test pinning the cap. The cap rises only through a later proven probe.
   - A shorter GTD re-posts on expiry: `on_order_expired` → `_close_rest(..., redecide=True)` (`strategy.py:808-809, 831-842`). `_post` re-calls `gtd_expire_ns` (`:555`), and the `expire_ns <= now_ns` refusal (`:556-558`) is kept.
   - The echo check is not the safety mechanism. A mismatch leaves the order AMBIGUOUS and resting (`client.py:8288-8293, 3650-3681`).
   - This is a `src/` change on the arm branch, so it rides the full gate in step 2.

---

## r2.2 amendment (coordinator, 2026-10-27; peer-reviewed by prediction-market-reviewer + python-reviewer, both APPROVE-WITH-CHANGES applied) — pricing-path defect fix, replay parity restored

- **Defect SEL-1.** The live node priced from a Depth10 frame that contained its OWN resting order (a NO bid is a YES ask at `100 − bid_cents`); `selector.py:107-110` did not exclude it, contradicting `rule.py:94`. When our bid was the best NO bid it ratcheted one tick per frame toward the cap, each step a REPLACE, and the rung lost its slot to the next-ranked rung (LAX 10-26 `gte79f` @0.81 → REPLACED 16:56:57Z → slot to `lt71f` @0.89; 230 contracts printed at NO 0.81 at 17:10:37Z). The Stage 0 replay tape never held our orders, so the replay never did this. Slot reallocation itself is identical in replay and live (`fill_pass.py:318`, `selector.py:175-177`, pinned by `test_strategy_parity.py:200`).
- **Fix.** Commits 9142c717 + b639a015 (`feat/data-capture-and-risk`): `ladder_state.own_excluded` subtracts our resting qty at our level before pricing; a frame-keyed `departed` entry keeps a cancelled/expired bid excluded only while the stored frame is the one recorded at the close; frames stamped at or before `Rest.posted_ns` are never excluded against. Wrong exclusion can only LOWER the bid. Parity fixture now echoes our open orders into frames (assertions unchanged). Full serial gate EXIT 0 (29,510 passed). `selector.py`, `rule.py`, caps, θ, breakeven, cost, settlement, harm-stop: untouched.
- **Deployment.** Node hand-relaunched **2026-10-27 19:18:00Z** (pid 442853, log `breezy-trade-20261027T191800Z.log`) after today's 16:50Z and 16:51Z boots died on a venue-side `401` on `/v1/account/balances` (first 401 at 16:31:45Z; auth succeeded again at 19:18:02Z). Window lost: 16:52–19:18Z.
- **Pre-registration consequence.** Fills are tagged **pre-fix (≤ 19:18Z 10-27, n = 0)** and **post-fix** and are reported separately; the verdict never pools them without a stated sensitivity analysis. Thresholds (p0 0.8747, ≤1 loss in 37 settled station-days, day-21 rate check, day-75 hard stop, D1 harm stop) are unchanged. Sequential looks are not reset.
- **Residual (bounded, lowers the bid only).** A frame that arrives after the venue removed our order but before `OrderCanceled` makes `departed` record an already-clean frame; one foreign contract at that price may be subtracted for that frame. SEL-2 (`reconcile.py:74-75` spends a slot on a post `_post` then refuses) is open, not part of this amendment.
