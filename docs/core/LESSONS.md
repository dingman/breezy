# Breezy — Lessons

Binding rules earned from real mistakes on this project. If a proposed approach
violates an active lesson, halt and report rather than proceeding.

---

## L-1 — Validate the Nautilus null hypothesis BEFORE proposing to build, not after

**Date:** 2026-08-30. **Trigger:** operator correction.

### What happened

While sequencing post-backtest work, the coordinator produced a P0-P6 plan that
named four things to *build* — a data-client health watchdog, a catalog
conversion integrity check, a convert-and-prune retention job, and
portfolio-wide/daily risk caps — without first checking whether
`nautilus-trader==1.231.0` already provides them. Peer reviews were run and were
valuable, but every peer was asked to design *around* the assumed gap rather
than to test whether the gap was real. The operator caught it.

### Why this is binding

CLAUDE.md's Immutable Foundation already states the null hypothesis: assume
Nautilus provides the functionality until proven otherwise. The failure mode is
not ignorance of the rule — it is applying the rule at implementation time
instead of at *planning* time. By then the plan has already spent reviewer
attention on an architecture for something that may not need to exist, and the
"smallest correct extension" has been framed as an extension rather than as a
configuration change.

This is the same class of error the repo has hit before: `BACKTEST_VENUE_CONFIG`
and the harness exist precisely because Nautilus behaviour was assumed rather
than read, and the substituted errors were silent.

### The rule

Every increment in every plan carries an explicit **Null hypothesis** verdict
before it is reviewed or implemented, citing INSTALLED-SOURCE `file:line` under
`.venv/lib/python3.13/site-packages/nautilus_trader/`:

- **NATIVE — sufficient** -> name the class/method/config field; the increment
  becomes "configure X"; write no code.
- **NATIVE — insufficient** -> name what exists and state precisely where it
  stops short. Do not overstate absence to justify building.
- **GENUINELY ABSENT** -> say what was searched for and where, so the negative
  is credible; then propose the smallest correct extension.

Read the installed source. Never answer from memory or from general Nautilus
documentation — the API surface differs between versions, and a plausible-
sounding wrong answer here produces a parallel implementation of something the
framework already does.

### How to apply

- Load the `nautilus-trader-patterns` skill before answering any "does Nautilus
  do X" question.
- A brief that asks a peer to *design a solution* must first ask it to *test
  whether the problem is real*. Order matters.
- Treat "we need to build a supervisor/validator/aggregator/limit" as a
  red flag phrase: frameworks usually have these. Check `RiskEngine`,
  `Portfolio`, `TradingState`, `ParquetDataCatalog` and the live node/kernel
  before writing any of the four.

---

## L-2 — A native substitution is a UNIT change until proven otherwise (2026-08-30)

**What happened.** A null-hypothesis audit found that `PortfolioFacade.net_exposure` is
account-wide and therefore closes the cross-strategy exposure hole without building
anything. Revision 1 of `DATA_CAPTURE_AND_RISK_PLAN.md` accepted that as a pure
simplification and instructed: *"read exposure from `self.portfolio.net_exposure(...)`
rather than summing `qty × contract_size`."*

Two independent reviewers caught it. `MispricingContract.contract_size` is
**payout dollars per contract** (`bucket_contract.py:47-48`), so `risk.py:116-131`
measures caps in **max-payout** units. `net_exposure` is **mark-to-market**. At a 0.05
bucket price the substitution loosens every cap **20×** — shipped as a null-hypothesis
win. The characterisation test written to catch silent retuning could not have passed.

**The rule.** Before replacing a hand-rolled computation with a native one, state the
UNIT of both and prove they match. "Nautilus already computes this" answers *whether*
a number exists, never *what the number means*. The null hypothesis is about
capability; it is silent about semantics, and semantics is where the money is.

**How to apply.**
- Any increment that swaps a local calculation for a framework call carries a line:
  `unit before = X; unit after = Y; equal because <reason>`. If X != Y it is a
  behaviour change, declared as one — not a refactor.
- Declare the system's exposure unit ONCE, in the plan, before any cap is designed.
  See `DATA_CAPTURE_AND_RISK_PLAN.md` §2.3.
- A characterisation test only protects a refactor if the refactor is genuinely
  behaviour-preserving. If it cannot pass, that is the signal — not a test to adjust.

**Related.** The same review pass found the audits were right about four native
*mechanisms* and wrong about the *degree* of two (`TradingState.REDUCING` does not
deny an opening BUY from flat; the free-balance guard is conditional on
`not allow_borrowing`). Degree is where a native verdict fails. Hence the binding
test-doctrine rule: every "NATIVE — configure" verdict gets a contract test that
EXECUTES the native path and asserts the outcome.

---

## L-3 — A plan whose end state is not the goal state is not a plan (2026-08-31)

### What happened

Asked why the build was taking so long when Nautilus "already has almost everything",
three independent investigations converged on an answer nobody had noticed: the active
plan, `DATA_CAPTURE_AND_RISK_PLAN.md` §5, is a five-to-six-week ordered sequence
(`P0 → P1 → (P2 ∥ P5-probe) → P5-fix → P4 → P3a → P3b → P6 → P7`) that, **executed
perfectly and to completion, still ends with a bot that cannot place an order.**

`grep -rn "LiveExecutionClient\|ExecutionClient" src/` returns **zero hits**.
`safety.py:8` describes itself as "The single **future** chokepoint" and
`assert_live_order_submission_permitted` has no production caller — only a re-export
and its own tests. The entire order-egress workstream lived only in Phase F of
`GO_LIVE_PLAN.md`, a document dated 2026-08-26 whose code-state audit had gone
wholesale stale and which was therefore no longer being read.

The plan had survived four adversarial peer reviews and a full revision-2 rewrite.
None of them caught it, because **every review asked "is what is written here correct?"
and none asked "does what is written here add up to the goal?"**

### Why this is binding

This is the single largest schedule finding in the project so far, and it is not a
coding error — it is a planning-topology error. Each increment was individually
well-justified, well-evidenced, and correctly sequenced against its neighbours. The
defect existed only in the *gaps between* increments, which is exactly the place no
increment-level review looks.

It also explains the measured effort profile: ~40% self-imposed process and ~28%
rework, against ~22% genuine domain difficulty. Rigour was being spent generously on
the increments we already knew how to specify, while the one workstream nobody had
scoped stayed invisible — and being unscoped, it never competed for attention.

The failure mode generalises: **work that has never been decomposed is work that never
appears on the critical path**, so a plan will systematically under-schedule precisely
what it understands least. Difficulty and visibility are inversely correlated here.

### The rule

Every plan states its GOAL STATE as a falsifiable predicate, then proves — explicitly,
in the plan — that completing the listed increments reaches it. Absent that proof the
plan is a list of good ideas, not a route.

### How to apply

- Each plan opens with: `GOAL STATE: <predicate>` and `WALK: <increment> → … → GOAL`,
  where the walk is checked end-to-end, not increment by increment.
- Add the reviewer's second question. Increment review asks "is this correct?";
  **plan review must separately ask "what is NOT here, and would its absence stop the
  goal?"** Reviews that only audit written text cannot find omissions — the prompt must
  name the omission hunt as its own task.
- **Suspect the workstream you cannot yet decompose.** If a plan is precise for eight
  increments and silent on a ninth, the silence is the signal: that is the long pole,
  not a detail to fill in later.
- A plan that cites another plan for a whole workstream has a dependency, not a
  delegation. Verify the cited document is still live — `GO_LIVE_PLAN.md` was being
  relied on for Phase F while its own audit had been stale for five days. Stale
  documents do not announce themselves; a superseded marker is now mandatory the
  moment a plan's factual claims are found wrong.
