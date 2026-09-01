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

---

## L-5 — A state document that outgrows re-verification becomes a source of false claims (2026-08-31)

**Date:** 2026-08-31. **Trigger:** operator challenge ("PROGRESS.md at 1400 lines feels
like a waste of context space, what value is it actually providing to us?").

### What happened

`docs/core/PROGRESS.md` had grown to 1401 lines / 76 KB — 31 status-marked headings of
which 11 were already closed, plus resolution narratives, evidence summaries duplicating
`docs/evidence/`, and post-mortems duplicating L-1..L-4. In the same session it produced
**three false claims** that were acted on before being caught:

- It recorded `calibration_mean_reversion` as "blocked on liquidity". The real gate is
  `SHORTS_DISABLED`, which fires in the decision layer *before* any liquidity check.
- It recorded `forecast_revision` as "REFUSED, naked short". Commit `4a1280f` had
  flipped `allow_short` to `False`, silently converting that loud abort into a counted
  refusal. A live re-run confirmed the record was stale.
- It carried `[BLOCKER] B-1 — No venue market data has ever been captured` and
  `[LOW] lint-imports has no configuration`, both of which reality had already closed.

Severity tags (`[HIGH]`, `[MEDIUM]`) were also used as *labels on closed work*, so the
file could not be skimmed for what was actually open.

### Why this is binding

Length is not a cosmetic property of a state document — it is what makes the document
wrong. Nobody re-reads 76 KB on each update, so entries are appended and never
reconciled; the file accumulates claims that were true once. A state document that
cannot be re-verified in one pass will drift, and drifted state is worse than absent
state because it is trusted.

The cost compounds: `/execute-backlog` Phase 0 dispatches an agent whose entire job is
to read this file, and the skill's own `PROGRESS_DONE>30` volume gate exists precisely
to force consolidation before execution.

### The rule

`docs/core/PROGRESS.md` tracks **OPEN state only**, under a hard budget of
**250 lines / 12 KB**, enforced by `.claude/hooks/progress-size-gate.sh`
(`PostToolUse` on `Write|Edit`, exit 2).

- An item **leaves the file when it closes.** Never rewrite it as a `[CLOSED]`
  narrative — the commit is the record.
- **Never restate evidence** in it; link `docs/evidence/<file>.md`.
- **Never restate a durable rule** in it; that belongs here in LESSONS.md.
- **Severity tags mark OPEN items only.**
- Superseded history goes to `docs/core/archive/`, never deleted outright.

### How to apply

- Before adding to PROGRESS.md, ask what can be *removed* in the same edit.
- Treat a status claim older than the last relevant commit as unverified until re-checked
  against code or a live run — see [[verify-agent-claims-against-artifact]].
- If the size gate blocks a write, consolidate; do not raise the budget.
- The same failure mode applies to any long-lived state doc, not just this one.

## L-6 — Promoting a shared flag to a kill switch inherits every producer (2026-09-01)

**What happened.** `79b9b44` made a dead market-data feed shut the node down and
exit non-zero, reading the existing `is_degraded` flag as the fatal signal. That
flag had THREE producers, not the two the change reasoned about: reconnect
exhaustion (`websocket.py:699`), supervisor death (`:710`), and
`_watch_for_silent_subscriptions` (`:795`) — one subscribed slug producing no
inbound frame within 60s. The third is an ordinary overnight condition in a thin
book. With ~60 weather markets subscribed, the first quiet one would have ended
an 8-hour capture around minute one, exiting 1 with "feed lost and not
recoverable" — a false statement, and a null capture that would have been read
as a dead market.

**Why it got in.** The flag was SAFE to share while its only consumer was inert:
producer 3's comment (`websocket.py:791-793`) explicitly justified reusing
`is_degraded` rather than "adding a second, unpolled signal", and it was right
at the time — the consumer set `_safe_mode`, which is written and never read.
The defect was not introduced by the producer or by the consumer. It was
introduced by the CHANGE IN WHAT THE FLAG MEANT, which no single site records.
The aggregator's own docstring (`:946-951`) still described the flag as "ANY
shard has abandoned reconnection" — it never mentioned producer 3 — so the
blast radius was invisible from the exact place the new consumer read it.

**The rule.** Before wiring an existing boolean to an irreversible action
(process exit, shutdown, halt, liquidate, alert-the-operator), ENUMERATE ITS
WRITERS — every assignment, not just the one you are reasoning about — and
classify each as fatal or not. A flag's docstring is not the enumeration; the
assignments are. If any writer is a routine condition, the flag is a
health*indicator*, not a kill switch, and needs the fatal class split out. Ask
"was this flag safe only because nothing important consumed it?" A signal that
has never had teeth has never been pressure-tested for precision.

**Corollary for reviews.** "Fail closed" is only correct when the signal means
what the action assumes. Fail-closed on an imprecise signal is not conservative
— it converts routine noise into an outage, which is strictly worse than the
silent failure it replaced.

## L-7 — Public information has no offer side (2026-09-01)

**What happened.** `cli_settlement_print_lock` was built on the thesis that the
book has not yet absorbed the final CLI print. On the first admissible run,
Nautilus submitted 0 orders. The reason was not a gate: on all five stations the
bucket containing the printed value carried **0 asks across 3332 depth rows**,
with bids of 0.99 x 7682 on the NYC winner. The losing rungs mirrored it --
asks at 0.01 in huge size, no bids. The strategy identified the correct contract
every single time and could not buy it.

**The rule.** A strategy that acts on information ALREADY PUBLIC to the venue is
not competing on speed or accuracy -- it is asking someone to sell it a contract
that is known to pay $1. Nobody does. Before designing any strategy, ask what
the COUNTERPARTY believes at the moment of the fill: if the answer is "the same
thing we believe, from the same public source", the offer side will be empty and
the edge is unharvestable regardless of how correct the model is.

**Corollary — a settlement-truth edge must be priced BEFORE settlement is
knowable.** The `p_stable` measurement (99.989%) was never wrong; it was a
measurement about a moment at which no trade is available. Measured certainty
and executable certainty are different quantities, and only the second pays.

**Method note that made this legible.** Two independent nulls landed on the same
window (no legal window, and no ask). Because 90 per-decision records were
persisted with the FIRST blocking gate, the null was decodable offline instead
of mute -- `RefusalCounter` was EMPTY, since nothing reached the decision layer.
A null with no persisted inputs would have been indistinguishable from a dead
market. See [[verify-agent-claims-against-artifact]]: the 0-ask count was
confirmed independently through the native catalog reader before being acted on.
