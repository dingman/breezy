# CLAUDE.md — Breezy

You are working on **Breezy**, a weather-prediction trading bot whose objective is to achieve increasing return on investment through disciplined, data-driven trading.

Breezy will initially trade on **Polymarket.us** and later expand to **Kalshi.com**.

## Immutable Foundation

Breezy is built natively on top of **Nautilus Trader**.

**Nautilus Trader is immutable. Never modify, patch, fork, bypass, or reimplement its foundation.** Breezy may only extend Nautilus Trader through its intended native extension mechanisms.

Always begin from the null hypothesis:

> **Assume Nautilus Trader already provides the functionality we need until proven otherwise.**

Before creating any new infrastructure, abstraction, service, adapter, model, or framework component:

1. Investigate the relevant Nautilus Trader functionality and extension points.
2. Determine whether the requirement can be satisfied through existing native capabilities.
3. Reuse or extend those capabilities whenever possible.
4. Build something new only when there is concrete evidence that the required functionality does not already exist or cannot be achieved through native extension.

Prefer the smallest correct extension. Avoid duplication, parallel architecture, speculative abstractions, and unnecessary complexity.

## Main Session Role

The **main Claude session is a coordinator only**.

It must delegate **all implementation, investigation, code analysis, testing, debugging, research, and other non-coordination work** to sub-agents and the **Codex Claude Code plugin**.

The main session may:

* Decompose objectives into tasks.
* Assign work to appropriate agents.
* Provide context and constraints.
* Review and synthesize agent results.
* Resolve conflicts between findings.
* Coordinate sequencing and integration.
* Maintain architectural consistency.

The main session must **never perform non-coordinator work itself**, even when the task appears trivial.

## Engineering Priority

For every decision, optimize in this order:

1. Preserve Nautilus Trader's immutable foundation.
2. Reuse native Nautilus Trader capabilities.
3. Maintain correctness and trading-system reliability.
4. Improve Breezy's ability to generate increasing risk-aware ROI from weather prediction.
5. Keep extensions simple, testable, observable, and exchange-portable for the eventual move from Polymarket.us to Kalshi.com.

When uncertain, investigate and delegate rather than invent.
