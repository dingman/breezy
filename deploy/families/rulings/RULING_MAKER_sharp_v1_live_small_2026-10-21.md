# RULING — pm_us_no_maker_sharp_v1 live qty-1 maker bids (2026-10-21)

Family `pm_us_no_maker_sharp_v1`. The sharp rule as built (`SHARP_V1`): qty-1 resting GTD BUY_NO bids. Live GTD is capped at 4 h (P3 PASS, `docs/evidence/P3_GTD_PROBE_2026-10-23.md`).

Existing operator caps are unchanged and are not restated. `allow_short` stays False. Nautilus Trader is not modified. The NO-SEND test firewall is not modified.

## Cost

Cost per fill is a flat 0.01 USD. No rebate is credited toward PASS.

## Gate

The unit is the settled station-day. A station-day is a LOSS if any fill on it loses, otherwise a WIN. An unsettled fill holds its station-day out of the count.

One evaluation, at exactly the first 37 settled station-days. No re-test at 38, 39, or later.

PASS = at most 1 loss, and net per contract > 0. Net per contract > 0 is a safety clause, not the inference.

Null p0 = 0.8747 (mean stress-fill bid 0.8647 + 0.01 over 17 in-sample sharp fills). P(PASS | p0) = 0.0449.

Early FAIL on the 2nd settled loss. Read the D1 artefact by hand daily after the 12:50Z D1 producer run. On that 2nd settled loss, call `set_family_halt_cli`, then the stop/rollback procedure below.

STOP at day 21 if fewer than 8 settled station-days, or if the rate is below 0.5/day. That STOP is inconclusive, not FAIL. Hard stop at day 75.

## Harm stop (loss bound only)

The existing D1 maker loss-stop rule stays, as a loss bound only. It is not this test's PASS/FAIL. Quoted from `src/breezy/strategy/no_ladder_maker/harm_stop.py` (T1 fires on the 3rd loss and halts):

> FAIL if ANY: (T1) L >= 3; (T2) n >= 3 and the one-sided 95% Clopper-Pearson upper bound on W/n < w*; (T3) n >= 4 and cumulative realised net PnL after fees <= -w*.

## Stop / rollback

1. Cancel per order id, not by empty-slug cancel-all.
2. List the venue's open orders and require zero on our slugs.
3. `set_family_halt_cli` additionally. It is a veto, not a cancel. Never use it instead of the cancels.
4. Restore the orders-off drop-in (`fq-v1-halt-orders-off.conf`) and its `DROPIN_ALLOWLIST` row, together with its test.
5. Stop the node and confirm DISPOSED.
