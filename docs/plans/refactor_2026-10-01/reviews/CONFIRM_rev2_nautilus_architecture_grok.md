I'll re-read Rev 2 and the prior NautilusTrader architecture review, then check each required revision against the new plan only.## Nautilus architecture confirmation — PLAN Rev 2

Read-only against Rev 2 and the prior review (NautilusTrader 1.231.0). No tests, no edits. One new claim was checked in the worktree.

| # | Prior required revision | Rev 2 |
|---|---|---|
| 1 | **MAJOR.** R1.2 is not a pure move. Callback only submits; death handling stays `call_soon_threadsafe`; observation fail-closed, inflight lock, deadline timer, and CRITICAL strings stay identical; assert the callback mutates no store. | **ADDRESSED.** Appendix A (not in the sequence). Constraints at (c), including the store-mutation assertion. `test_live_timer_thread_affinity.py` is correctly scoped as a Nautilus pin, not acceptance. |
| 2 | **MAJOR.** Rewrite the signing row. 32-byte parity matched; 64-byte key does not. Signer stays for the cage, the skew window, and key shapes. Narrow BC-11. | **ADDRESSED.** §1.2 signer row; BC-11 requires a key-shape migration. |
| 3 | **MAJOR.** Live fee hook is `execution/client.pyx:165-194` (base returns `None`). Backtest gate stays `backtest/engine.pyx:651`. Do not send `calculate_commission` to `live/execution_client.py:343`. | **ADDRESSED.** §1.2 fee row withdraws the old cite. §3.1 keeps `generate_*` on the exec-client row and `FeeModel` / `engine.pyx:651` on the fee row. |
| 4 | **MAJOR.** `AlertState` is not JSON. `evaluate` stays on the loop thread. Do not move the `ts_init` nudge with `_alert_conditions`. CT-9 is not the R3.6 pin. | **ADDRESSED.** R1.5; R3.6 (nudge stays; dependency is CT-4); C3 detaches CT-9. |
| 5 | **MINOR.** "Redis only" is the kernel wire-up. Postgres exists and is unwired. No Postgres step. | **ADDRESSED.** §1.2 cache row; BC-8 is "not recommended." |
| 6 | **MINOR.** `orders_inflight` misses `INITIALIZED` and overlaps `orders_open` on `PENDING_*`. `cache.pyx:5906` is stale. | **ADDRESSED.** §1.2 orders row. |
| 7 | **MINOR.** Strike the public-markets-socket premise (`websocket.py:1278-1280`). The 10-sub cap is not native. | **ADDRESSED.** §1.2 remaining candidates and §3.1 strike the premise; BC-11 no longer includes that swap. The cap sentence is not repeated; the supervisor is still retained. |
| 8 | **MINOR.** `Component.degrade` is already used. No design change. | **ADDRESSED.** §1.2 health row (`exec/client.py:5950`). |

**New objection.** Appendix A (b) and §1.3 rank 4 say the observation actor "settles twice" and that inflight "goes negative by one per poll." That is false. `_submit` increments once (`nws_observation_actor.py:231-232`). `_settle` runs on exactly one branch (`:237`, `:248`, `:252`, `:257`, or `:267`). The same exclusive shape is in `nbm_forecast_actor.py:251-284`. Preserving a negative inflight would invent a bug. Strike that parenthetical before any R1.2 characterization. The real differences (inflight lock, `_rebuild_trusted = False` at `:266`, the second deadline timer, CRITICAL strings) are already listed under (c).

`LiveRiskEngineConfig` in §3.1 is a real live-config name, not a new miss.

**Verdict for Rev 2: APPROVE-WITH-CHANGES.**
