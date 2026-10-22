# P3 r2 verification — security-reviewer (incl. P4 GTD-cap question)

**VERDICT: r2 closes all six r1 changes (APPROVE-WITH-CHANGES, 1 nit). For P4, choose (a): cap live GTDs at now + 4 h.** Confidence 80.

**r1 changes 1–6 against r2**
1. Authorization (r2 L62): fixed. It is now its own named exception with a $0.02 ceiling, the deviation from the audit's 2 h is stated, and a heads-up is promised.
2. Hard kill (L65): fixed. The GTD of at most 4 h is the backstop.
3. `left_to_gtd` never polls (L21): fixed.
4. Node appearing: **dropped.** r2 removes the per-heartbeat node probe, and the one-order, 4 h window is now justified by the supervisor schedule (L36). That is acceptable at $0.01, but L36 should be checked against `trade_supervisor_core.py:37-40,668-689` at implementation time.
5. Order A: removed with its risk. Fine.
6. Exact-G shape match (L16) and the named pin tests (L29-32): fixed.

The cancel budget of 3 is also fixed. Two nits to keep:
- The loss claim of $0.01 depends on the fee rounding to $0.00 (L63). State the $0.01 fill-loss cap as the ceiling and don't rely on the rounding.
- L54 says a 4xx is INVALID unless it explicitly rejects the GTD, but "explicitly" is not defined. Pin it to a specific error-code or message match before the run.

**P4 question: (a) is the simpler and safer choice.**

Re-post after expiry:
- `strategy.py:808-811` in `/home/jon/breezy-arm-int` handles `on_order_expired` with `_close_rest(..., redecide=True)`.
- `on_order_canceled` at `:791-793` does the same.
- A re-decide posts a new rest (`strategy.py:~555`, `gtd_expire_ns` called per post).
- The "midnight cut re-posts" note in `rule.py:233-235` is about the replay/live difference, and the strategy re-decides on the expired event.

So a 4 h cap just causes a re-post at the next decision, which is cheap and bounded. The replay's median rest is about 1,100 s, with a maximum of about 3.4 h. The cap rarely binds, and when it does the cost is a re-post and a repeat of queue priority.

Why not (b):
- An echo check only catches a venue that clamps at confirm. A venue that accepts a 7.2 h GTD and then silently expires it early is not caught.
- The P3 PASS licenses 4 h only (L4, L82). Anything beyond that is unproven.

Change for (a):
- Add `now_ns + P3_LICENSED_GTD_NS` to the `min()` in `gtd_expire_ns` (`rule.py:231-238`) as a named constant, with a comment citing the P3 evidence.
- Keep the existing `expire_ns <= now_ns` refusal at `strategy.py:556`.
- Add one test pinning the cap.
- Keep the echo check as a cheap log or alert for a venue clamp. Do not make it the safety mechanism.
- Raise the cap only through a later proven probe.