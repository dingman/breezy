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

It must delegate **all implementation, investigation, code analysis, testing, debugging, research, and other non-coordination work**. The main session never performs that work itself.

### Delegation Order

Route every unit of non-coordinator work in this order:

1. **Grok Build CLI first.** The `grok` CLI (via the `grok-build` plugin) is the
   default destination for **building the bot** — implementation, refactor, and
   build-fix work — and is preferred for investigation and analysis too.
2. **Codex second.** The Codex Claude Code plugin, when grok is unusable or the
   work suits it better.
3. **Claude sub-agents third**, as the final fallback — see the trigger below.

**Fallback trigger.** Move down the order only when the current destination is
genuinely unusable, evidenced by one of:

* The CLI is not installed, not on `PATH`, or not authenticated (`grok models`
  reports "not authenticated"; `codex:setup` reports `ready: false`).
* Usage, quota, or rate limit is exhausted.
* A hard tool error or PreToolUse block on that path.
* The work is Claude-native coordination surface neither CLI can address
  (writing briefs, merging agent findings, plan/spec authoring).

Report the fallback and its trigger — never fall back silently, and never let
"the CLI was busy" become an excuse to do the work inline.

### Grok delegation guardrails (BINDING)

`/grok-build:delegate` and the `grok-delegate` agent **default to `--write`**:
the sandbox flag is dropped entirely and the run is auto-approved with
`--cwd <repo>`. A write-capable external agent can therefore violate this
repo's invariants silently. Every grok delegation must:

1. **Carry the hard invariants in the brief**, restated explicitly — Nautilus
   Trader is immutable; `allow_short` stays `False`; never weaken or delete a
   safety, settlement, or contract test to go green; never assign a value to an
   operator-reserved control (max daily budget, max per position); never touch
   live-trading enablement or the NO-SEND execution-egress firewall.
2. **Be read-only unless the task is actually a write.** Investigation,
   analysis, and review must explicitly request read-only, because write is the
   default — silence grants write access.
3. **Be verified against the artifact, unconditionally.** A grok "done" or
   "tests pass" is a claim, not evidence: read the diff, re-run the gates
   yourself via `scripts/ci/run_tests_no_egress.sh`, and require real RED→GREEN
   output. Delegation moves the work, never the accountability.

**Accepted consequence of this decision:** grok transmits repo content — diffs,
untracked files, and for `/grok-build:import` the full Claude transcript — to
xAI. That is inherent to using it and is an accepted operator decision, not a
defect to re-litigate. It does not relax the NO-SEND firewall, which governs
what the *test and execution* paths may reach, and stays in force.

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
