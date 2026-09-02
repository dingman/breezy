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
`breezy-trade` entry point.

**Amendment 2026-09-01:** that entry point now EXISTS —
`breezy-trade = "breezy.runtime.trade_cli:main"` (`pyproject.toml:240`, EXEC SPINE R-2,
commit b5c7eb9) — alongside `build_trade_node_config`, so the node-config half is closed too.
What remains absent is any execution CLIENT: `src/breezy/adapters/polymarket_us/exec/` is
empty. The lesson is unchanged — a `[V]` belongs on the inference, not on the command. L-3's substance survives — no increment built the
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

**Amendment (2026-09-01, same day).** "Public" does not mean "officially
published." Re-reading the same tape by timestamp: the NYC winner carried no ask
at 03:30Z -- **3 h before its final printed, and ~10 h after its climate day had
ended.** The book had already fully repriced while the official record did not
yet exist. So the moment that empties the offer side is the moment the outcome
becomes PHYSICALLY DETERMINED and observable to anyone watching the same
instrument, not the moment a bulletin is issued. Any future strategy that names
a publication event as its trigger is anchored to the wrong clock and will
arrive late by exactly the publication lag. This is the measurement that
generated H3 (`docs/strategies/archive/H3_intraday_running_max_lock.md`).

## L-8 — A 0-row read is not a quiet market until the tape is verified (2026-09-01)

**What happened.** A quote-tape capture was killed uncleanly. The file was not
corrupted in the ordinary sense -- `close()` only appends the end-of-stream
marker, so a clean EOF at a message boundary still reads fine. But when the file
ended MID-MESSAGE, `ParquetDataCatalog._read_feather_file` caught
`(pa.ArrowInvalid, OSError)` and returned `None` (`parquet.py:2795-2800`), which
`convert_stream_to_data` turned into `continue` (`:2644-2646`). Conversion then
reported SUCCESS over an empty catalog: 228 KB on disk, 0 rows delivered, no
exception, no log line.

**The rule.** In this system a null result has two indistinguishable causes --
the market did nothing, or the tape silently failed to load. They are
indistinguishable *by construction*, because the loader's failure path is a
`continue`. **Never interpret a 0-row or low-row result as evidence about the
market until the tape behind it has been independently verified** (row counts by
file, timestamp coverage against the intended window, and a truncation
preflight). Verification precedes interpretation; a strategy verdict built on an
unverified tape is a verdict about the recorder.

**How to apply.** Run `breezy-quote-tape-preflight` over the catalog before any
run that will produce a strategy verdict, and quote its per-file status
(`EMPTY_FILE` / `EMPTY_STREAM` / `INTACT` / `TRUNCATED` / `UNREADABLE`) in the
evidence document alongside the result. Loss from an unclean death is bounded by
the write buffer (~8 KB), not the flush interval -- salvage recovered 491/500
records -- so a truncated tail is usually recoverable and should be salvaged
rather than discarded. Pinned by
`tests/contract/test_quote_tape_unclean_shutdown.py`.

### L-8 amendment — a 2xx is not a datum (2026-09-01)

The same failure has now occurred on the HTTP surface, and the coordinator
committed it. The Open-Meteo probe report records
`q3_archive_depth_2019` as **HTTP 200, 5079 bytes**
(`docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z/PROBE_REPORT.md:39`).
Reading only that row, the coordinator asserted "forecast archive depth
confirmed back to 2019" and propagated it into two agent briefs.

The very next section of the same report says the step is **partial**: "2xx, but
the payload did not carry the datum this step was designed to extract"
(`:62`). Only `q3_archive_depth_2022` ANSWERED, with `rows=168` (`:61`). The
report even states the conclusion explicitly at `:83` — coverage is
"NON-CONTIGUOUS ... an unexplained gap, not a clearance". A dedicated bisect
probe then measured `2024-01-01 -> 0/168` for all four models, bracketing the
boundary between 2023-12-09 and 2024-01-01.

**The rule, generalised:** a status code, a byte count, and a non-empty response
are all compatible with zero usable data. **Every coverage or availability claim
must cite a ROW COUNT, never a status code, and must be read together with the
report's own answered/partial classification.** The probe had already done the
work correctly; the error was entirely in the reading.

Corollary for briefs: a fact asserted into a subagent brief propagates at the
speed of dispatch and is expensive to recall — two briefs and one external
design run were seeded with the false 2019 claim before it was caught. Verify a
load-bearing premise BEFORE it enters a brief, not after the returns land.

## L-9 — On this venue the near-certain rung is never offered; stop designing lock strategies (2026-09-01)

**What happened.** Three independent strategy families, three refutations, one
mechanism.

| Strategy | Trigger | Result |
|---|---|---|
| `cli_settlement_print_lock` | after the FINAL CLI print | winner rung **0 asks / 3332 rows**, 5 stations |
| H1/H2 `running_extreme_lock` tails | after a preliminary print | fired **0/4**; venue lists tails 4-8 F outside the day |
| H4 headroom-1 afternoon lock | after the diurnal peak, BEFORE any print | condition held **375/375, 381/381, 372/372**; ask present **0.00%** |

H4 was designed specifically to escape the first two by triggering EARLIER, on a
physical observation rather than a publication. It failed identically. The
adjacent rungs were offered on ~100% of rows at 0.01-0.02 throughout: the ladder
is liquid, and the offer is absent on exactly the rung our model likes.

**The rule.** On this venue, a LONG-ONLY TAKER cannot harvest certainty. Every
strategy of the form "identify the outcome that is nearly determined, then buy
it" requires a counterparty to sell a contract known to pay $1, and no such
counterparty exists at any hour we have observed -- before or after the print,
before or after the physical lock. Moving the trigger earlier does not help,
because the market maker reprices off the same public observations we do and is
not slower than us (Breezy polls CLI on a 300 s timer; it is structurally
slower). **Do not design another lock strategy. The null is not "we picked the
wrong hour"; it is "this trade has no seller."**

**Where the remaining edge must live.** If certainty is unsellable, the only
harvestable region is where genuine UNCERTAINTY remains -- an offer exists
precisely because the outcome is still in doubt. Winning there requires being
BETTER CALIBRATED than the market while both sides are still uncertain, which is
a forecasting edge, not a lock. Note what that implies and do not skip past it:
Breezy currently ingests **no forecast data at all**, so the entire strategy
family that could work is blocked on a capability that has been deprioritised
twice (programme P2/P3). Any next hypothesis should either live in that family
and carry forecast ingestion as its Gate 0, or state explicitly why it escapes
this lesson.

**Method note.** All three nulls were decodable because per-decision inputs were
persisted and the tape was verified before interpretation ([[L-8]]). The H4 run
also shows the right shape for a cheap kill: measure whether the ORDER IS
AVAILABLE before measuring whether it is profitable. An absent ask is not a
pricing problem that a better model or a lower break-even can solve.

### L-9 amendment — the cheap side is mostly a lottery already lost (2026-09-01)

L-9 sent the programme toward "where uncertainty remains", and the first reading
of the microstructure pointed at the deep books on the cheap rungs (median
~35,991 contracts offered at 0.01, against 0.58 at 0.99 on winners). The
coordinator framed that inversion as the tradeable region. **That framing was
wrong and must not be repeated.**

Those deep 0.01 offers are overwhelmingly **post-peak**: rungs the climate day
has already missed. Their true probability is residual METAR<->CLI basis plus
late-rise, not "a 1% event" — buying them is buying a lottery that has already
lost, and paying the 0.01 tick floor as the entry fee. H1/H2 are the same object
in costume: listed tails 4-8 F from the printed high, triggered 0/4, asks at
0.01 correctly pricing a non-event.

Nor is the pre-event cheap rung automatically juicy. At 24 h the forecast error
is roughly sigma ~= 2.8 F, so a 6 F tail is about `1 - Phi(6/2.8) ~= 1.6%`
against a 1% minimum tick — **fair to slightly expensive after fees**, not a
100:1 mispricing. A tick floor that coarse means a genuine sub-tick edge cannot
even be expressed; the existing engine's `p_floor = 0.01` is an accidental
confession of exactly that.

**What survives:** only the PRE-EVENT (D+1) cheap-open book, which is
structurally different from the post-peak dump and is at present essentially
unmeasured. **Gate it before building for it.** The measurement (K1) is: first
cheap-open ask per `(station, climate_day, rung)` on the D+1 book, scored
against the eventual CLI integer final, Wilson 95%. If the upper bound sits at
or below break-even, the calibration family is dead too — and that result is
worth far more than the forecast-ingestion build it saves.

**The ordering rule this reinforces:** measure whether the trade is AVAILABLE,
then whether the population is REAL, and only then build the model. The
programme has twice run the settlement-side test first and terminated at "gate
PASS, economics unknown."

## L-10 — A brief's vocabulary becomes a subagent's verified fact (2026-09-01)

The EXEC SPINE plan asserted, as a **CONFIRMED present** Nautilus native, "the
native Command-outcome taxonomy … is exactly `{terminal, retryable,
AMBIGUOUS}`", and used it to JUSTIFY CUTTING SCOPE ("more is speculative").

**No such taxonomy exists.** `AMBIGUOUS|Ambiguous` and `retryable|RETRYABLE` each
match in **0 files** across installed `nautilus_trader` 1.231.0.

**Provenance is the lesson.** The coordinator wrote that three-word set into the
commissioning brief's non-goals list — not as a claim about Nautilus, merely as a
convenient label for a scope cut. The planner read authoritative-sounding
vocabulary in an authoritative document and promoted it to a verified native.
Neither party checked. The upstream cause was the brief.

Worse, the same session had ALREADY recorded this failure shape: the L-8
amendment's own corollary says "verify a load-bearing premise BEFORE it enters a
brief, not after the returns land." It was written and then violated within the
hour — this was the **third** false premise seeded into a brief in one session
(the others: the Open-Meteo 2019 archive depth, and the D1 walk-the-book cost
characterisation that a marketable IOC LIMIT makes impossible).

**The rule.** Anything a brief states in the register of fact — a version, an API
name, a taxonomy, a coverage span, an execution semantic — must be VERIFIED
before dispatch or explicitly marked `UNVERIFIED — confirm before relying`. A
subagent cannot distinguish the coordinator's shorthand from the coordinator's
knowledge, and it has every incentive to treat the brief as ground truth.

**The countermeasure that worked.** The mandatory adversarial peer-review caught
it, which is precisely why the planning gate is not discretionary. The near-miss
is instructive: an ordering test HAD already been implemented from this same
unreviewed plan. It was test-only and harmless, but the review gate was skipped
to get there. **Run the gate before implementing, not after — including when the
increment looks too small to need it.**

**Also record the missed real native.** `live/retry.py:65 RetryManager[T]` and
`:242 RetryManagerPool[T]` DO exist and are NOT wired into `LiveExecutionClient`
(0 references). It is the first thing an implementer reaches for, and wiring it
to `submit_order` on a venue with **no client-order-id** auto-resubmits and
silently doubles the position. Fabricating a native hid a real one that is
actively dangerous. See [[validate-nautilus-before-planning]].

---

## L-11 — Claiming a gap where a native exists is the same defect as claiming a native where none does (2026-09-01)

**Rule.** Every "Nautilus does not provide this" verdict is a null-hypothesis
claim and carries exactly the same burden of proof as "Nautilus provides this":
a `file:line` that was actually opened, plus a search that could have found the
opposite. A FALSE GAP is harder to catch than a false native, because the code
you then write **works** — nothing fails, no test goes red, and the duplication
is only visible to someone who goes looking.

**What happened.** `EXEC_SPINE` Revision 1 justified a Breezy-owned durable store
with *"`CacheConfig(database=None)` is memory-only, so a restart orphans the
position"* — stated as a property of Nautilus. It is a property of **our
configuration**. Nautilus persists both natively: `cache/cache.pyx:393-394`
restores orders and `:1366-1368` rebuilds the venue-order-id index;
`cache/database.pyx:709-755` replays stored `OrderFilled` events and reconstructs
the `Position`, so `avg_px_open` is derived from fills and survives byte-exact.
The store may still be the right call — Redis is the only backend
(`system/kernel.py:312`, `:324-329` raises otherwise) and we decline that
dependency — but **"we decline a native" and "no native exists" are different
statements, and only one of them was true.**

**Why it matters beyond tidiness.** L-10 recorded a fabricated native that caused
a wrong scope CUT. This is the mirror: a fabricated gap causes a wrong scope
ADD. Both survive review by sounding like the conclusion of an investigation that
never happened. The operator caught this one by asking directly, which is not a
control we can rely on.

**How to apply.** State the verdict in one of exactly three forms, never a fourth:
`NATIVE CONFIRMED (file:line)` · `NATIVE EXISTS, DECLINED BECAUSE <cost>
(file:line)` · `GENUINE GAP — verified absent (file:line of the search, plus the
positive control)`. "Declined" must name what is being given up. A plan that
reads "no native exists" where the truth is "a native exists and costs a Redis
dependency" has hidden a decision the reader is entitled to re-make.

**The tooling trap that makes false gaps cheap here.** Grep's *directory
recursion* under `.venv/` is silently blind — ripgrep honours `.gitignore:1`
(`.venv/`), so a recursive search of installed Nautilus returns **0 matches with
no error**. Measured: `rg -l 'Nautech Systems'` under `nautilus_trader/live/` → 0
files; `--no-ignore` → 15. File-scoped Grep works. **A bare "0 matches" never
closes a null hypothesis in this repo** — re-run with shell `grep -r` and a
positive control in the same command, e.g. `expiration_ns` = 0 across `live/`,
`execution/`, `portfolio/`, `risk/`, `trading/` is meaningful only beside
`expiration_ns` = 63 in `model/instruments/`.

**Evidence:** `docs/evidence/native_reuse_audit_2026-09-01.md` — five-seam audit
of every Breezy surface against its nearest native, including the inverse finding
that Breezy configures **no** native risk caps at all. See [[L-10]],
[[validate-nautilus-before-planning]], [[native-substitution-is-a-unit-change]].

## L-12 — Widen an exact-set barrier, never relax it

Two barriers in this repo assert **set EQUALITY**, so legitimate new work turns
them RED and the tempting fix is to loosen the assertion:

- `tests/unit/test_weather_data_type_barrier.py:94` (W1) does not cover a new
  weather record class.
- `tests/unit/test_probe_containment.py:297-310` asserts set equality, so adding
  a third endpoint turns it RED.

The same shape governs the execution-egress firewall: N2, X3 and E0-INERT in
`tests/unit/test_execution_egress_firewall_guard.py` are exact-set equalities
whose docstrings require a new `exec/` module to update the set **in the same
commit**.

**The rule: WIDEN the expected set, never relax the comparison.** Never convert
`==` to `in`, to a subset test, or to an allowlist. An equality that a reviewer
must consciously update is the mechanism — it is what makes a new
execution-egress module impossible to land silently. Relaxing it keeps the test
green while deleting the only thing it was protecting.

Corollary, learned landing R-3 (2026-09-01): membership in an exact set proves a
module **exists**, never that it is **inert**. E0 listed modules; it took
E0-INERT to assert that none of them can reach the network. When you widen a set,
ask what the set actually proves — and whether the property you care about is
asserted anywhere at all. Both X1 and X3 had been **silently vacuous**, scanning
a package no test imported.

## L-13 — An extremum statistic is not comparable across different sampling cadences (2026-09-02)

The CLI-basis boundary study measured `P(CLI_final >= R_h + 1)` per station,
where `R_h` is the ASOS RUNNING MAXIMUM. NYC returned 56-60% against 16-26% for
the other four stations, and it passed the pre-registered bar by nine times over.
It was an artifact. KNYC reports **hourly**, ~24 observations/day; the others
report every 5 minutes, ~321/day.

**A running maximum computed from a sparse series is biased LOW**, because fewer
samples means fewer chances to catch the peak. Every statistic of the form "did
the truth exceed our observed extremum" is therefore biased HIGH by exactly the
sparsity, and the bias does not announce itself — the cell had n=1808, a tight
Wilson interval, and was stationary across five years. Power, precision and
stability are all properties of the SAMPLE; none of them detects this.

**The rule: before comparing an extremum-derived statistic across sources,
compare the sources' sampling cadences. Where they differ, DOWNSAMPLE THE DENSE
SOURCE to the sparse one's resolution and recompute.** That experiment is cheap,
it is causal, and it settles the question in one run. Here it moved LAX 25.27% ->
64.34%, MIA 25.50% -> 64.29%, SFO 22.29% -> 60.92%, MDW 15.55% -> 54.98% — every
dense station landing on NYC's measured value. That is not evidence NYC is
special; it is proof the metric reads cadence, not weather.

Corollary, and the more general trap: **a filter that selects almost everything
is not a condition, and a statistic conditioned on it is unconditional.** The
same study framed its result as a late-day effect over hours 17..23, but
`P(R_17 == R_23)` is 99.40% at LAX — the running max had already converged, so
the hour filter added no information and the number was the unconditional
CLI-vs-ASOS basis wearing a condition's clothing. Before believing a conditional
edge, measure how much the condition actually excludes. If a "condition" is true
of ~99% of the sample, the edge it appears to isolate belongs to the population,
and is very likely already in the price.

See also L-1 (validate before building) and the standing note that an
underpowered verdict describes the sample, not the world — this is its mirror
image: a WELL-powered verdict can also describe the sample rather than the world.

## L-14 — A barrier list is DERIVED from "what would refuse this?", never recalled (2026-09-02)

Three plan revisions across four increments each stated which barrier tests a
change would touch, and each was wrong the same way. Increment W's list read
"N2 exact-set pin ... Nothing else." Building it turned FOUR barriers red:
`PERMITTED_EXECUTION_CLIENTS` (`test_polymarket_us_readonly_guard.py:734-743`,
whose docstring said outright "Factories stay banned outright"), its meta-pin
(`test_cage_rule_constants_are_pinned.py:511,777`), and
`TestTheReadOnlyCageIsDeclaredNotDefaulted` (`test_runtime_node_config.py:347`),
the last tripping TWICE — once on the build-site count, once on the per-field
rule. Auditing the rest of the plan on the same suspicion moved one increment's
list from two entries to NINE.

**Why the error is systematic rather than careless.** A barrier list written
from memory is a list of the tests the author READ. The barriers that actually
gate a change are the ones that would REFUSE it, and several of those fire on
properties nobody looks up: an equality over a pin TABLE that every new constant
must join; a COUNT pin that trips on each new allowlist ENTRY, so two entries
are two changes and not one; widened/narrowed-neighbour tests that come free
with every new pin; and scans whose roots (`src` + `scripts` + `tests`) are
broader than the package under edit.

**The rule: derive the list by asking "what would refuse this?" and answer it by
running the suite against a deliberately broken version of the change — not by
recalling which files were read.** A barrier list is a falsifiable claim, so
test it. In this repo the cheap derivation is: grep the barrier files for the
constant, the class base, the path prefix, and the config field the change
touches, then check each hit for a count pin and a meta-pin above it.

Corollary, and the reason this matters beyond tidiness: an under-enumerated
barrier list makes a change look SMALLER than it is at planning time, so the
increment is sized wrong, and the widenings get done under implementation
pressure rather than under review. That is the condition under which someone
relaxes a comparison instead of widening a set — which is exactly what L-12
exists to prevent.
