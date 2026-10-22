# P3 r1 review — Grok (venue mechanics / simplicity)

I'll review the GTD horizon plan against the maker-control code and the audit evidence, read-only, and judge whether it answers the question without extra machinery.The plan is loaded. Next I’ll check its claims against the maker-control script, the live GTD rule, and the B2 evidence.The worktree has no code index, so I’ll read the control scripts and the cited evidence directly.**VERDICT = APPROVE-WITH-CHANGES**

One qty-1 BUY NO at 0.01, GTD = H, read at a few fixed times, is the whole experiment. The draft answers that, then adds a second order, a 15-minute heartbeat, eight fake-clock cases, and a horizon evidence mode. That extra surface is a defect on a one-shot worth cents. Do not add a websocket-drop leg.

Facts that hold: the resting body is nine keys and has no client order id (`submit_chain.py:113-144`); the send path refuses a GTD past 600s (`_maker_control_core.py:49,401-410`, `polymarket_us_maker_positive_control.py:497-498`); B2 passed, and slug cancel-all left the other sibling NEW (`maker_positive_control_20261022T075159Z.json`: S-2 PASS, `s2_b_state_after_cancel_all`, `slugs_share_event`). `gtd_expire_ns` is min(09:00 LST, 10h permit, UTC midnight) (`rule.py:231-238`, `safety.py:172`), so a 16:50Z boot really does ask for about 7.2h. Any open order blocks arming (`trial_day_latch.py:1540-1541`). A and A' were 404 then 200; B's first GET was already 200. Supervisor: stop 16:40Z, launch 16:50Z, relaunch only until 17:00Z, midday watch only until 01:00Z (`trade_supervisor_core.py:37-40,668-689,1205-1253`). SKILL.md L333/L335/L339 was not in the tree; the code matches the claim.

Required changes:

1. Drop order A (36,000s echo, then cancel). It never rests, so it cannot measure a horizon or stand in for the live 7.2h/10h request (`plan` L28, L95). A PASS licenses only the H you actually waited.
2. Drop the 900s heartbeat, the per-beat node probe, and "every heartbeat is NEW" as a PASS term (`plan` L30, L54). GET after confirm, once mid-rest, at G−30s, and at G+60s. A missed beat is not a venue result. This window is outside automatic relaunch.
3. Cut the eight-case suite, the `mode=horizon` evidence branch, and the custom 60-GET budget. Keep the unflagged 600s pin and one test that a GTD above the cap is refused before signing.
4. Any create 4xx is INVALID, not binding F1 (`plan` L3, L61), unless the response says the GTD itself was rejected. B2 already created this shape at HTTP 200.
5. Require start + H + slack < 16:40Z. The written window allows 12:00Z and H = 6h, still open at the 16:50Z launch (`plan` L15, L44). `--select-only` uses the 600s close check (`_maker_control_core.py:992-993`), so it does not dry-run this slug rule.
6. Pass the long ceiling into listing cleanup (`positive_control.py:1008-1009` vs `_maker_control_core.py:1199-1200`). Do not wait out a failed cancel on the 14×20s lapse poll (`positive_control.py:970-987`); that cannot cover H, and a leftover blocks the next arm.

Websocket: leave it out. A REST probe never opens the private session, and `UNSOLICITED_CXL_REASON_CONNECTION_LOSS` is documented but unverified. The 16:40Z stop can overlap a Pacific 09:00 LST expiry (17:00Z) by about 20 minutes; that is audit item 4, which the plan already defers.

Also cut Step 0 and the H formula. Fix H at 2h, the audit item. The fee on a 0.01 fill banker's-rounds to $0.00 (`fees.py:593-605`), so two total losses are about $0.02, not $0.04.

Confidence: 84.
