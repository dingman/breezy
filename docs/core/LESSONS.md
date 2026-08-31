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

---

## L-4 — A fix is a diff against one finding; a document is a set of claims (2026-08-31)

### What happened

`ORDER_EGRESS_PLAN.md` went through three adversarial review rounds. Round 1: 16
blocking findings. Round 2: 5 criticals, with 15 of 16 round-1 findings genuinely
closed — converging. Round 3: roughly 7 criticals and 10 highs, and **most were
created by revision 3's own fixes**. Round 2 had already shown 3 of its 5 criticals
were introduced by round-1's repairs. Two consecutive rounds is a pattern.

Four of round 3's findings share one mechanism. A revision changed a fact in the
place the finding pointed at, and did not change the other places asserting the same
fact:

- §4.2 deleted `cost_cap = payout_cap × price` and gave E-5 an AST scan banning it;
  E-5's body still computed it. An implementer following the increment trips the
  increment's own scanner.
- The settlement source was reverted in E-3 and E-6; `:473` and `:2028` still
  described the pre-revert arrangement, and `:473` is the reuse table an implementer
  reads to decide what to reuse.
- G0's coverage line omitted the increment that actually registers the exec client.

The remaining round-3 findings share a second mechanism: a fix that satisfies its
named finding while perturbing a neighbouring design area. Moving position-attribution
to a later increment closed the phantom short and created a backward dependency.
Adding a fifth authority type closed a bypass and made `POST /v1/orders` reachable
under a second, budget-invisible type.

### Why

Revising against a block list optimises hard against the named findings. Nothing in
that loop re-runs the document's global consistency checks, so the edit is locally
correct and globally wrong. The larger and more cross-referenced the document, the
worse the ratio: this one designed the settlement identity, the authority-type
algebra and the container/ordering simultaneously, so every fix perturbed two other
areas.

### The rule

**After any revision, sweep for propagation before claiming a finding closed.** For
every FACT the revision changed, enumerate every site in the document asserting that
fact and verify each one changed. This is mechanical and cheap; it would have caught
three of round 3's findings for the cost of three greps.

**And when review rounds stop converging, the document is the defect.** Two
consecutive rounds where repairs generate more criticals than they close is not a
signal to revise harder — it is a signal that the scope is too entangled to converge.
Cut it at a principled seam and plan the halves separately, after the earlier half
exists as code and answers the later half's questions.

### How to apply

- A revision report names, per finding, the sites it swept — not just the site it
  edited. "Fixed at `:1296`" is incomplete; "fixed at `:1296`, swept `:550`, `:558`,
  `:2028`" is the claim.
- Re-review every revision. Never assume a fix is a monotonic improvement; in this
  document it was not, twice.
- Track findings-per-round. Rising counts mean stop revising and re-scope. The seam
  should be one the domain already provides — here, NO-SEND / SEND, because settlement
  is not needed until a position can exist and multi-type authority is not needed
  until a write endpoint exists.
- Prefer several small plans over one large one for anything spanning more than one
  design area. The 2246-line document was not thorough; it was three plans sharing a
  namespace.

### Correction to L-3

L-3's "third recurrence" was recorded as *the trading process itself does not exist*,
on the strength of `grep "TradingNode(" src/` returning zero hits. **That inference was
false.** The repo passes the class rather than calling it — `node_factory: NodeFactory
= TradingNode` (`quote_tape_cli.py:195`, `cli.py:147`), then `node_factory(config);
node.build(); node.run()` (`:151-156`). A real `TradingNode` is built and run today by
the quote-tape process. The true gap is narrower and still real: no trading-ROLE node
config (`build_quote_tape_node_config` pins `exec_clients={}`, `strategies=[]`) and no
`breezy-trade` entry point. L-3's substance survives — no increment built the
trading-role container — but its headline overstated the gap, and the overstatement
was carried into a plan as a `[V]`-tagged fact.

**The generalisable half:** `[V]` belongs on the INFERENCE, not on the command that
produced it. A grep result is evidence; what it implies is a separate claim needing
separate proof. Zero hits for `Foo(` does not mean `Foo` is unused — it means `Foo` is
not called *in that syntactic form*. See [[verify-agent-claims-against-artifact]].
