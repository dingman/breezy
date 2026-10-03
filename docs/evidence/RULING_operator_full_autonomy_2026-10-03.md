# RULING — operator objective: full autonomy (2026-10-03)

**Operator instruction (verbatim):** "The objective is that the trading bot operates and trades
completely autonomously. Store each area in detail in the backlog. Then create peer-reviewed plans for
each area and associate them together. Success can only be claimed for each area when the execution
results in a score of 3, on that scale of 0-3."

## What this rules

1. The programme goal state is **autonomous operation and trading**: capture, labelling, retraining,
   evaluation, promotion and demotion, drift response, and rollback run unattended, with no human or
   agent commit in the loop.
2. The success measure is the 0–3 scale defined in
   `docs/plans/backlog/AUTONOMY_2026-10-03/README.md`. An area closes only at an independently
   scored 3 on its **executed** result.
3. This supersedes the "live-trading enablement of any family is operator-only" wording in
   `docs/plans/backlog/AUDIT_2026-09-21/README.md` in one respect only. A **pre-registered** promotion
   policy, authored as its own ruling under AUT-5, may promote and demote families and artefacts inside
   the already-enabled live envelope. It likewise supersedes decision **D11** of
   `docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md` (arming a new family is operator-only)
   within that envelope. The code-only live-orders allowlist is replaced, by a one-time reviewed change
   under AUT-5, with admission by that policy ruling.

## What this does NOT change

- The two operator caps (max daily budget, max per position) stay operator-only and are never assigned
  by the bot.
- The master real-money enablement, the permit mechanism and the NO-SEND egress firewall are not
  automated by this ruling.
- `allow_short=False`, Nautilus immutability, and the safety, settlement and contract tests are unchanged.
- PREREG statistical semantics still change only by ruling. The bot executes pre-registered policy and
  never invents policy at runtime.
