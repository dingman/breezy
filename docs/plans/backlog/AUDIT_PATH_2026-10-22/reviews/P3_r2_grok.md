# P3 r2 verification — Grok (incl. P4 GTD-cap question)

I'll review P3 r2 against the six required changes from my r1 review, and check the new code claims in the arm-b2 tree before answering the GTD question.The six r1 changes are loaded. Next I’ll check the r2 code claims in the arm-b2 worktree, including the live GTD rule.The arm-b2 tree has no code index, so I’ll read the cited symbols directly.**VERDICT = APPROVE-WITH-CHANGES**

Changes 1–5 are met. One order; a PASS licenses only the 4 h waited. No heartbeat: confirm, one mid-rest GET, G−30 s, G+60 s. Four tests, not eight; `Budget(max_creates=1, max_cancels=3)` leaves `MAX_GETS` at 40. A create 4xx is INVALID unless the body rejects the GTD. Start must finish before the 16:40Z stop, and `--select-only --horizon` uses the same `now+H` exclusion. Both re-digest tests exist and pin `c73801fa…`. H = 4 h instead of the audit's 2 h is an explicit departure, not one of the six.

1. Horizon cleanup still misses the path that needs it. `is_own_probe_shape` has no `exact_gtd_ns`; it accepts `now−60s .. now+660s` (`_maker_control_core.py:1182-1200`). Its only caller is `_cleanup_by_listing` (`positive_control.py:1008`), which runs only on `create_in_doubt` (`:969`), set when `rest()` raises (`:657-659`). `sent_gtd_ns` is stored only after `rest()` returns (`:665`). Persist `body["goodTillTime"]` before `post_order` (`:526-531`) and match that stored value within 1 s (`GTD_ECHO_TOLERANCE_NS`), not a recomputed now+H and not the 660 s window. Also lift the second 600 s gate in `_build_resting_body` (`:497-498`); `assert_gtd_within_ceiling` (`core:401-410`) is not the only refuse. Skipping the 14×20 s lapse poll (`:971-987`) is right.

2. The supervisor sentence is wrong. Stop 16:40Z, launch 16:50Z, and boot relaunch only until 17:00Z are `trade_supervisor_core.py:37-40` and `decide_relaunch` `:676-682`. Midday watch is not 16:50Z→01:00Z and is not in `:668-689`. It opens at 17:10Z (`:50`, `next_due` `:1243-1253`) and closes at 01:00Z the next day (`:1205-1209`). The probe window before 16:40Z is still empty. Fix the sentence. "Latest start 12:25Z" equals 16:40:00, so it fails the strict `<`; use 12:24Z. Not load-bearing: G is ~16:25Z and launch is 16:50Z.

**P4: (a).** `gtd_expire_ns` is `min(hard_cancel, permit_expiry_ns, end_of_utc_day)` (`no_ladder_maker/rule.py:231-238`). At 16:50Z the midnight term is ~7.2 h. Add `now_ns + 4h` to that `min()`. A shorter GTD re-posts: `on_order_expired` calls `_close_rest(..., redecide=True)` (`strategy.py:808-809`, `:831-842`), and `_post` calls `gtd_expire_ns` again (`:555`) and still refuses `expire_ns <= now_ns` (`:556-558`).

(b) is not safe. `resting_echo_matches` fails when `|seen−sent| > 1s` (`submit_chain.py:825-827`). Confirm then returns `RESTING_CONFIRM_HOLD` and does not cancel (`client.py:8288-8293`). The order stays AMBIGUOUS and keeps resting (`:3650-3681`). An echoed 7.2 h that expires early is not caught at all.

Confidence: 86.
