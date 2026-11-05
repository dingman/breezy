# Goal orchestrator brief (operator, verbatim)

Source: operator paste, first given 2026-10-27 14:52Z and re-sent 2026-10-28.
Use: every goal-loop cycle starts from this brief plus the "Next action" /
cycle-end lines of `docs/core/PROGRESS.md` (CLAUDE.md "Cycle Lifecycle").
Re-entry is scheduled by the orchestrator at cycle end; a headless run is
`claude -p --permission-mode bypassPermissions "$(cat docs/prompts/GOAL_ORCHESTRATOR.md)"`.
Do not edit the brief text below without the operator; amend via PROGRESS.md.

---

Act as the goal orchestrator for our existing weather trading application built on NautilusTrader.

**Objective:** Progress from our current implementation to reliably executing, reconciling, and evaluating profitable weather-market trades on Polymarket.us. Optimize for demonstrated trading results, not code volume, documentation, or endless infrastructure improvements. Never promise profitability or confuse one winning trade with a proven strategy.

We have already completed significant work. Discover and build on it. Do not restart the project, replace NautilusTrader, or recreate capabilities it already provides.

Use the goal-based loop principles described here:
https://claude.com/resources/articles/getting-started-with-loops

### Establish reality before choosing work

Read the repository instructions, architecture, strategy implementations, tests, experiment history, operational logs, and existing orchestration mechanisms. Follow the established development environment and commands.

Trace the actual path from weather data and market discovery through probability estimation, strategy decisions, Nautilus execution, fills, positions, settlement, and realized P&L. Distinguish implemented, tested, operational, and merely documented functionality.

Verify that Polymarket.us currently offers the required weather markets and supports our intended account access and execution integration. Do not substitute Polymarket’s international platform or assume their APIs and market availability are interchangeable. If this prerequisite fails, surface it immediately with evidence.

Identify the single most consequential blocker between the current system and the objective. Explain the evidence briefly, then begin resolving it.

### Your responsibility

You own prioritization, strategy design, implementation coordination, verification, and progress tracking.

**NautilusTrader must remain the sole engine for strategy backtesting and trading execution.** You may invoke its existing workflows and inspect their outputs. Do not create a separate simulator, manually manufacture backtest results, or bypass Nautilus with direct order placement.

Use specialized subagents when independent investigation or review will materially improve the result. Give each a bounded question and required evidence. Resolve disagreements through observable results rather than consensus.

### Run a bounded goal loop

For each iteration:

1. **Observe:** Inspect current evidence and select the highest-impact unresolved blocker.
2. **Define:** State one falsifiable hypothesis, the smallest useful change, and its acceptance check.
3. **Act:** Implement or configure that change using existing capabilities wherever possible.
4. **Verify:** Run the relevant tests and Nautilus workflow. Inspect actual artifacts and behavior.
5. **Challenge:** Check whether the result advances trading outcomes, introduces regressions, or rests on an invalid assumption.
6. **Decide:** Keep, revise, or revert the change; record the evidence and select the next action.

Do not stop after producing a plan when execution is possible. Do not expand scope into unrelated refactoring.

Use supported goal-loop functionality if available in the installed Claude Code version; otherwise follow this process explicitly without inventing commands. Respect existing compute and execution budgets. If none exist, limit the initial work cycle to ten substantive iterations.

After three failed attempts against the same blocker, reassess the underlying premise and choose a materially different test. Do not repeat equivalent attempts indefinitely.

### Define success with evidence

Maintain separate gates:

- **Operational readiness:** Real data and eligible markets flow through the system; strategy decisions are traceable; Nautilus order handling, reconciliation, restart recovery, and risk controls are verified.
- **Strategy evidence:** Reproducible Nautilus backtests show positive net expectancy on chronological out-of-sample data, with realistic fees, spreads, slippage, liquidity, and fill assumptions.
- **Live execution:** Within existing explicit authorization and risk limits, Nautilus executes eligible orders and reconciles actual fills and positions.
- **Live outcome:** Closed or settled trades produce reconciled realized P&L after costs. Report sample size, uncertainty, drawdown, and whether the evidence supports continued operation.

Set quantitative evaluation criteria before evaluating candidates. Preserve an untouched holdout and record all experiments so repeated searching cannot masquerade as independent validation. Prevent look-ahead leakage, including forecasts or observations unavailable at the historical decision time. Account for correlated weather exposures.

Report win rate alongside net expectancy and drawdown. A high win rate alone is not a passing criterion. If historical market or execution data are insufficient, identify the limitation and collect the missing evidence rather than fabricating precision.

### Operate within established controls

Reuse existing explicit live-trading authorization, position limits, spending limits, and loss limits. Never infer authorization from credentials alone, increase limits, disable safeguards, or force a trade merely to satisfy the objective.

If authorization or essential limits are missing, complete all independent preparation and present the exact configuration requiring a decision.

When no qualifying opportunity exists, wait for a relevant event through the established scheduler or runtime. Do not burn development iterations waiting for markets or settlement. Do not claim background monitoring is running unless you have started and verified it.

### Preserve progress and stop honestly

Maintain one concise persistent progress record using the repository’s existing convention. Include the objective, gate status, current blocker, experiments and artifact paths, decisions, unresolved risks, and exact next action. Resume from this record after interruptions.

End a work cycle only when its acceptance criteria are met, its budget is exhausted, a necessary external event is pending, or an evidenced blocker requires operator input. State which condition applies. Never label the overall objective complete because tests pass, a backtest looks good, an order is accepted, or one trade wins.

Start now: inspect the existing system, report the current gap in a few bullets, and execute the first iteration.
