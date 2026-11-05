# P2 r2 verification — Grok

I'll review the revised P2 plan against the three required changes and check the new claims in code. Reading the prior review and the r2 plan first.The three required changes are in the r2 text. Next I’ll check the new code claims: the D+1 gate, the production `evaluate` call, the fee, MIA 13Z timing, and the scored end date.**VERDICT = REQUEST-CHANGES**

Instant (b) is gone. A miss of +0.005 is no longer a deletion: FAIL needs both wider-CI upper bounds below 0 and both samples evaluable. The book rule is one snapshot, within 10 minutes; a one-sided YES ask matches `on_order_book_depth`. 09:00 LST on D−1 does pass the D+1 check (`local_standard_date` + 1 day, `decision.py:216–218`, `:277–281`). That is not the instant the strategy traded.

**Required changes**

1. **Gate on the launch, not 09:00 LST.** Launch is 16:50Z (`trade_supervisor_core.py:38`); the permit lasts 10h (`safety.py:172`). The plan’s own log shows the LAX `lt97f` Take at 2026-10-04T16:51:03Z, with MDW evaluated in the same second. 09:00 LST is 17:00Z at LAX/SFO, 15:00Z at MDW, and 14:00Z at MIA, so the 17:00–17:10Z window misses that fill and MDW/MIA are scored before the process exists. `permit_covers=True` admits those takes. Use the first Depth10 snapshot at or after 16:50Z on LST date D−1, within 10 minutes, one snapshot, else drop. That instant is still D+1. The MIA “13Z + 60 min = 14:00Z” risk is real only at 09:00 EST (`forecast_point.py:168`); by 16:50Z that cycle is in or already late.

2. **Do not stamp 0.0695 on the whole window.** The cash fee is θ·qty·ask·(1−ask), half-even to the cent (`fees.py:313–351`, `:597–605`). The 0.64 fill charged $0.02, which is 0.0695, not 0.06. θ is 0.06 before 2026-09-17T00:00Z, refused until 17:00Z, then 0.0695 (`fees.py:93–122`). Use `taker_fee_coefficient_as_of`. `evaluate` hurdles on unrounded `venue_fee_prob` plus slippage (`decision.py:337–345`); round only the cash P&L.

3. **Drop the parity STOP.** It cannot pass, and r1 already cut it. The file is under `logs-archive/`, not `logs/`; logged `p_hat` is 0.9924313174096698, while `S0D_TOLERANCE` is 1e-9. Also drop `systemd-run` and the deletion file list. Keep the sha pin, the identity check, the null check, and `min(day) > 2026-06-30`.

End date D = 2026-10-13 is right. At the gate only 13Z on 10-12 is visible, not 19Z or 01Z (`pno_store.py:144–147`). Composition passes a default `LadderEvConfig()` (`trade.py:854–873`). `_p_hat` is the same `evaluate` shape, not the same inputs.

**Confidence: 88.**
