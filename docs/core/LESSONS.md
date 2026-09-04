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

---

## L-15 — When a barrier's scope is decided by a classifier, RUN the classifier (2026-09-02)

The R-6a increment plan stated its barrier basis as: "`backtest_order_guard.py`
carries **0** venue references, so B4 never classifies it and V1-V4 do not
apply." Both halves were false. The file carries **6** venue references, and
`is_venue_touching()` returns **True** on it — classifier rule **C5**
(`_VENUE_NAME_RE = /polymarket/i`, `test_polymarket_us_readonly_guard.py:230`)
matches the venue's NAME in *any* `ast.Constant`, and a module docstring **is**
an `ast.Constant`. The file had been inside barrier B4's scope the entire time.

The conclusion — "no barrier files change" — happened to survive, because the
increment adds no write verb. That near-miss is the point: a false premise that
reaches a true conclusion is not caught by the conclusion being true.

**Why the derivation failed even though L-14 was followed.** L-14 fixed *not
deriving the list*. This is the next failure inward: the list WAS derived, but
one input to it was **guessed by reading the file** when the thing that decides
it is an **importable, executable function**. Nobody has to reason about whether
a docstring counts as a string constant, or whether "0 venue references" is even
the right question — `is_venue_touching(path, ast.parse(src))` answers it in one
line, and `find_write_egress_violations(path, src)` returns the current
violations as data:

```python
import ast, sys; sys.path.insert(0, "tests/unit")
from test_polymarket_us_readonly_guard import is_venue_touching, find_write_egress_violations
```

**How to apply.** Before asserting in any plan, brief, or review that a barrier
does or does not apply to a file: import the barrier's own predicate and call it
on that file. Report the measured boolean, not a reading of the source. If a
barrier's scope cannot be evaluated by calling something, say the scope is
UNKNOWN rather than inferring it — an inferred exemption is the one that gets
discovered by a red gate at landing time.

**The trap this particular case was hiding.** Because the file *is* in scope,
rule V3 applies to it: V3 refuses any `ast.Attribute` named `post`, `put`,
`patch`, `delete`, or `request` — **syntactically, on any object at all**.
Nautilus's `MessageBus` has a `.request()` method. An installer written as
`msgbus.request(...)` would trip V3 inside a file the plan called exempt, and
the tempting "fix" — narrowing the classifier or shrinking the attribute set —
is precisely the [[L-12]] violation: widen an exact-set barrier, never relax the
comparison. Use `msgbus.subscribe(...)`; the code bends, the barrier does not.

Related: L-12 (never relax an exact-set barrier), L-14 (derive the barrier list,
never recall it).

---

## L-16 — A raise inside a Nautilus `LiveClock` timer callback is silently discarded (2026-09-02)

Reproduced directly against the pinned wheel (`nautilus_trader==1.231.0`): a
`LiveClock` default handler that raises has its exception **vanish**. No
propagation out of `asyncio.run`, no `sys.unraisablehook`, no
`threading.excepthook`, exit code 0, process continues.

```
asyncio.run RETURNED NORMALLY (no propagation)
callback fired: 1 | unraisablehook: 0 | threading.excepthook: 0
```

The dispatch is Rust-side, so the exception never reaches a Python frame that
would surface it. `Actor.register_default_handler(self.handle_event)`
(`common/actor.pyx:722`) wires `on_time_event`-driven callbacks through this
same mechanism, so it generalises to any strategy acting on a timer — which is
the natural shape for a forecast-driven weather strategy.

**Why this matters beyond the one bug.** "Raise to refuse" is the idiom Breezy's
safety guards use, and it is correct in backtest, where a raise deterministically
aborts a single-threaded run. Live, the same raise has THREE different fates and
only one of them is loud:

| Path | Fate of the raise |
|---|---|
| Engine queue task | caught → `_handle_queue_exception` → `os._exit(1)` — process dies, but bypasses the CLI's `finally`/exit-code mapping, so the operator gets exit 1 with **no cause line** |
| `MessageBus.publish_c` dispatch | no try/except around `sub.handler(msg)`; unwinds into whichever frame published |
| **`LiveClock` timer callback** | **silently discarded — no signal at all** |

`graceful_shutdown_on_exception` defaults `False`
(`live/config.py:60,78,201`), and all three live engines end at
`os._exit(1)  # Immediate crash`.

**How to apply.** Never rely on a raise alone to inform an operator in a live
Nautilus node. A refusal must **write its own operator-visible record at the
moment it refuses** — latch the fault AND write the line to line-buffered stderr
right there — because the process may die without unwinding, or may not die at
all. The safety property (the order never reaches `cache.add_order`) survives on
every path; only the *observability* does not, and a safety control nobody can
tell fired is one you will believe never fired.

Corollary for reviewers: "an uncaught exception here kills the node" is a claim
about a specific dispatch path, not a general truth. Determine which of the
three paths applies before accepting it — and prefer reproducing it over reading
for it, as was done here. Related: [[L-15]] (run the executable oracle rather
than reasoning about what it would say).

---

## L-17 — A field present in every sample you have seen is not thereby REQUIRED (2026-09-02)

`parse_binary_option` treated `updatedAt` as required (`parsing.py:1281`). Every
market payload ever inspected carried it, so it looked mandatory. It is not:
the venue omits it on a market it has **never modified since listing**. Measured
live — of the 20 freshly-listed 2026-09-03 markets, **20/20 carried `createdAt`
and none carried `updatedAt`**. Older cohorts all carry it, alongside
`ep3SyncedAt` stamps, because by the time anyone had looked at them they had
been updated at least once.

**Why every sample lied.** The field appears after a STATE TRANSITION. Any
sample gathered from markets that have existed for a while is drawn entirely
from the post-transition population; the pre-transition state is invisible
precisely because it is brief and early. `updatedAt`, `resolvedAt`, `closedAt`,
`firstFillAt`, `lastTradeAt` are all this shape. **Optionality is a property of
the producer's contract, not of your sample**, and a sample can only ever
establish presence, never necessity.

**What made it total rather than partial.** One unparseable market aborts the
WHOLE discovery cycle, so a single never-updated market blocked all 30 for ~24
minutes. **Measured correction — the first draft of this lesson overstated it,
and a lesson about overstating from a sample must not itself overstate:**
capture did NOT go to zero. Already-subscribed markets kept recording (132 files
in that window, including quote ticks); an aborted reload raises before
`_reconcile_discovered_subscriptions`, so it can only cost NEW subscriptions.
The real loss is that the new cohort was never subscribed, so its opening price
discovery — the most informative and least contested segment there is — does not
exist on a forward-only tape.

**How to apply.** For every `_require`, ask: *what lifecycle state of this
record would legitimately lack this field?* Newly-created is the canonical
answer and the one your sample structurally cannot contain. Where a field is a
transition timestamp, prefer an explicit fallback to the creation timestamp
(a record never updated was last changed when it was created) over either
requiring it or defaulting to `0`/`now()` — **a synthesised timestamp silently
corrupts a tape, which is strictly worse than refusing it.** Widen exactly the
one field the producer has proven optional and no others ([[L-12]]).

**The forecasting failure worth keeping.** The triage that had just closed the
morning's listing-gap incident predicted "Breezy will pick the cohort up
automatically with no intervention." That prediction was confidently wrong, and
wrong for this reason: it reasoned from the 100 markets it had parsed
successfully, every one of them already updated. A verdict of "the parser is
proven healthy — 100/100 accepted" was true of the sample and false of the
population. When a component is declared healthy on a sample, state which
population the sample came from, and treat any *new* population — a fresh
cohort, a new venue state, a first-of-its-kind record — as unproven until it
arrives. Related: [[L-15]] (run the executable oracle), [[L-13]] (a statistic
is not comparable across the regimes it was not sampled from).

## L-18 — A counterfactual is a claim about a mechanism you have not run (2026-09-02)

Two of my own errors in one review round, same shape: I recorded what *would
happen if something changed*, as fact, without tracing the mechanism that would
have to carry it.

**Instance 1, the dangerous one.** `PROGRESS.md` stated that removing the R-4
standing refusal (`exec/client.py:1338-1350`) "**enables order sends**". False.
The signer permits only GET (`signing.py:84`), no write transport exists under
`src/`, and R-6.5/R-7 are unlanded — there is no send to enable. Removing R-4
would have deleted the only **denial** on the path, so a submitted order would
receive neither `OrderDenied` nor a send and would hang in flight silently.
The entry did not merely overstate a benefit; it inverted the sign. It made a
strictly-worse change look like the natural next step, and it had sat in the
backlog as a standing invitation to make it.

**Instance 2, cheap but instructive.** The T-1 plan required RED-7
(`PARTIALLY_FILLED`) to fail on the pre-fix tree. It cannot: `PARTIALLY_FILLED`
is already inside `is_open_c` (`base.pyx:421-430`), so the narrow query always
saw it. The widening's only status-visible change is `INITIALIZED`/`SUBMITTED`.
One look at the membership list would have caught it; instead the implementer
found it at the code, having first written a test that could not go red.

**Why this class survives review.** A counterfactual reads like an observation
and is graded like one. "Removing X enables Y" has the grammar of a measurement
but the content of a prediction, and nothing in the sentence marks which. Both
instances were **one grep from disproof** — membership of a status list, and
the presence of a write verb. Neither was hard; both were simply never run,
because the claim already sounded settled.

**The sharpest instance of the same family, found in that review.** A safety
control can be asserted and unenforced: `safety.py:668
assert_live_order_submission_permitted` — the operator-permit chokepoint for
live submission — has **zero callers in `src/`** (only a re-export at
`__init__.py:120`), and barrier B6/B7 actively *bans* it from acquiring one. It
reads in every document as the gate on live order submission. It gates nothing.
**A function with no caller is not a control**, however exactly it is named.

**How to apply.** Before writing that changing X produces Y — especially in
`PROGRESS.md`, a plan, or a commit message, where it becomes the premise of
someone else's work — name the mechanism that carries Y and check it exists.
Mark it `UNVERIFIED` if you did not. When citing a control as a cover, check it
has a **caller**, not just a definition and a good name; when asserting a test
will go red, check the predicate actually changes for the case you chose. Same
discipline as [[L-15]] (run the executable oracle rather than reasoning about
what it would say) and [[L-17]] (a sample establishes presence, never
necessity) — and the reason [[L-12]] insists a barrier is widened by measured
need rather than by argument.

## L-19 — Measure a blast radius by SIMULATING the change, not by counting call sites (2026-09-02)

Reviewing the T-4 plan, which changes `PortfolioSnapshot.equity` from
`float = 10_000.0` to `float | None = None`, the reviewer did not reason about
what would break. It patched `PortfolioSnapshot.__init__.__defaults__` to `None`
and the five `_equity()` bodies to drop their fallback, via a pytest plugin,
then ran the full suite against the unmodified repo.

That produced a number no census could: **16 failures, of which 15 were
`TypeError` at the arithmetic site and one was not.** The odd one out —
`test_calibration_mean_reversion_shorts_disabled_alert.py:193` — fails on
*assertions* instead (`refusals.total() == 0` -> 1, `len(orders) == 1` -> 0),
because its rig has no venue account. It is the **control** proving the
shorts-disabled alert tracks the permission rather than the market, so it must
be repaired with a stub account and never by relaxing the assertion. A grep for
`PortfolioSnapshot(` would have listed it among 89 sites with nothing to
distinguish it; a census of "sites relying on the default" would have missed it
entirely, because it *passes* `equity` explicitly.

**The count was also simply wrong by hand.** The plan said 88/39/49; the AST
census said **89/40/49**. The uncounted site re-fabricates the constant by hand
(`test_weather_strategy_quote_staleness.py:99`,
`PortfolioSnapshot(equity=10_000.0)`), so it would have survived the whole fix
as a live fabrication *and* been invisible to a structural guard on the default.

**A second finding of the same shape, about the enforcement itself.** The plan
leaned on strict mypy to prevent misuse of the new optional. Measured with a
repro: an unguarded read in another method IS caught — but
**`portfolio.equity or 0.0` type-checks clean** and silently restores the exact
fabrication the change removes, and mypy flags **zero** of the 49
default-reliant sites. The type change is a real but PARTIAL control. Claiming
a type makes an invalid state unrepresentable is itself a claim to check
([[L-18]]): `T | None` plus `or` is `T` again, with no diagnostic.

**How to apply.** For any change to a widely-constructed type's default or
nullability, spend the ten minutes to simulate it — monkeypatch the default,
run the suite, read the failures — BEFORE writing the scope section. The
failures that are not the expected exception type are the ones worth the whole
exercise: they are where the change alters *meaning* rather than merely types,
and they are exactly what a call-site census cannot see. And when a plan claims
the type system will enforce something, write the escape hatch out and check
whether it compiles.

## L-20 — The catalog you query is not the tape you capture (2026-09-02)

**Rule.** Before concluding that the quote tape lacks a window, a day, or an
instrument, compare the parquet catalog under `<catalog>/data/` against the
Arrow IPC streams under `<catalog>/live/<instance>/` — row counts per instance,
per data type — and run `breezy-quote-tape-ingest` (or the preflight) first.
An analysis that reads `data/` measures **what has been converted**, not what
was captured.

**Why.** M_A reported `n_afternoon = 0` — "the tape has no 12:00–17:00 LST
coverage" — and Grok's memo, my report, and a ten-line diagnosis brief were all
about to treat that as a capture defect. 199,079 `OrderBookDepth10` rows for the
09-01 afternoon were sitting in `live/5a111bca…`, unconverted, because
`convert_stream_to_data` had been run by hand exactly twice and
`quote_tape_cli.py` declares conversion out of scope. After conversion:
`n_afternoon = 4`, 9,588 qualifying snapshots, and the first non-dead signal in
the programme. The wrong reading would have cost nothing visible — it would
simply have kept the family "dead" for want of data that already existed.

**How to apply.** The six-hourly `breezy-quote-tape-ingest.timer` now bounds the
lag, and the live writer is skipped (no end-of-stream marker; convert only
after a clean SIGTERM). But the rule outlives the timer: any "the data is
missing" verdict names the layer it looked at, and a zero from a query is a
[[measure-catalog-freshness-with-epoch]]-class measurement bug until the
stream directory has been checked. Companion to [[L-18]]: "no coverage" is a
claim about a mechanism (conversion) that had not run.

## L-21 — A climatological base rate is not the comparator for a market price (2026-09-02)

**Rule.** When an archive-derived probability (unconditional on the day's
information) exceeds a venue ask by a wide margin, the default reading is
"the archive answers a different question," not "the market is wrong." The
statistic that can discriminate is the **realized** outcome rate of the trials
the screen would have taken, against `ask + fee`, at a sample size the kill
criterion names in advance.

**Why.** M_B's archive table said P(CLI max lands in the 2°F rung the running
max sits in at noon) has a Wilson-lower of 0.59 for MDW-SON, and the venue
priced that rung at 0.06 on 09-01 — a formal "edge" of +0.53. The table was
audited and reproduced exactly; nothing was wrong with it. The day settled two
degrees above the rung. A market maker prices off the forecast and the
warming trend; the archive pools every historical day regardless. Grok's
original kill sentence compared the archive bound to the ask and therefore
could neither fire nor confirm; it was amended to the realized hold rate
(kill n≥60, survive n≥150).

**How to apply.** Any screen built from history alone is a **selector**, never
the edge; write the kill in terms of what actually happened to the selected
trials. And do not fake the missing conditioning (forecast, trend) into the
screen after seeing a miss — that is moving the goalposts, and the forecast
family was killed for exactly the lack of that ingest. Companion to
[[L-9]] (three refutations of "identify the near-certain rung, then buy it")
and [[L-18]].

## L-22 — A safety primitive's exclusion must be unforgeable, not offered (2026-09-03)

**Rule.** When a library exists to prevent a double action (a submit-intent
latch, a writer lock, a kill switch), the mechanism that makes it exclusive
is part of the primitive's constructor, never a sibling helper the call site
is trusted to remember. If the object can be built without the lock, the
design has a fail-open path by construction, and no call-site discipline or
docstring closes it.

**Instance.** The first R-7 latch brief specified `SubmitIntentLatch(store)`
plus a separate `hold_submit_intent_process_lock()` context manager. The
security review reproduced two `arm()` calls both returning OPEN (get-then-set
with nothing binding the flock to the latch) and one arm overwriting the
other's durable record. Fix `5d41eaa`: `open_submit_intent_latch()` is the
only constructor, holds the flock for its lifetime, every method asserts it
is still held, and an instance mutex serialises the read-modify-write.

**Detection.** Any brief for a guard primitive that lists the lock as a
separate bullet from the guarded object. Ask: can the object exist unlocked?
If yes, rewrite before dispatch.

## L-23 — A configuration snapshot is not the effective runtime; the journal is (2026-09-03)

Hunting the missing 2026-09-02 station-day, a sub-agent read
`instrument_reload_interval_mins: null` from every recorder instance's
`config.json` and concluded discovery ran exactly once per process, so a cohort
listed mid-session could never be picked up. Confident, specific, wrong: the
recorder journal showed the reload loop firing 6-hourly and retrying every 60 s
after a failure (`quote_tape_cli.py:263` overrides the field at start-up), and
the venue had simply never listed a 09-02 cohort at all — a by-slug `404` with
09-01 and 09-03 as passing positive controls settled it.

**Why this is binding.** A persisted config field records what was *written*,
not what the process *does*; overrides, defaults resolved at construction, and
CLI flags all live between the file and the behaviour. The failure shape is the
same as L-8 and L-20: a plausible artefact standing in for the measurement. It
would have produced a "fix" (set the interval) that changed nothing and closed
the ticket on a gap the venue owns.

**The rule.** A root cause about *what a running process did* must cite the
process's own record — the journal, the emitted tally, the on-disk output — and
must survive a positive control. A config value, a docstring, or a default is a
hypothesis about behaviour, never evidence of it. Before naming a cause that
implies "we never asked the venue", prove the venue had something to give
(L-8): fetch the missing key by identifier and fetch its neighbours the same way.

**How to apply.** When a finding rests on a config or snapshot field, ask "what
line would this process have logged if that were true?" and go read it. When a
finding says "the data was never captured", classify it VENUE-NEVER-LISTED /
LISTED-BUT-FILTERED / LISTED-AND-ABORTED only after the by-identifier probe with
neighbours as controls. Related: [[L-8]], [[L-18]], [[L-20]].

## L-24 — A fixture that always satisfies an invariant never tests the driver that must supply it (2026-09-04)

**What happened.** The 6b paper-replay harness landed with 15 green unit tests,
three of them running a real `BacktestEngine`. The first real run over the
captured tape refused all 14 invocations at `SettlementInvariantError`: the
driver had never loaded the tape's `InstrumentClose` stream, so no tradeable
instrument could ever settle. Every unit fixture had been built with a close
record in hand, so the invariant was satisfied by construction and the driver's
omission was invisible to the suite. The invariant itself worked exactly as
designed; the tests around it had only ever fed it the happy input.

**The rule.** For every fail-closed invariant a driver must satisfy, the driver's
tests carry the NEGATIVE fixture (the input the driver is responsible for
supplying, omitted) and assert the invariant fires — and the driver's positive
path is exercised at least once against the real artefact, not only against
fixtures that pre-satisfy it. A refusal on first real use is a result (L-8,
L-18); a suite that never produced that refusal in miniature is the defect.

**How to apply.** When a brief names an invariant the new code must satisfy,
add a RED test titled "…still refuses when <the driver's input> is absent" next
to the happy path, and schedule one real-artefact run in the build sequence
before calling the increment done. Related: [[L-8]], [[L-18]], [[L-20]].

## L-25 — A fill better than the displayed ask is a defect signature, not price improvement (2026-09-04)

**What happened.** The first paper replay to reach a decision (MDW 2026-09-01,
`current_rung_hold`, instance `5a111bca`) scored one trial and printed
`slippage: mean=-0.11` — an execution 11 cents BETTER than the ask, presented as
favourable. A read-only reconstruction showed two driver defects and no price
improvement: `entry_ask` was the tape's FIRST quote (08:28 LST, 0.15), four
hours before the decision, while the strategy's own latch held the real
decision ask (0.06); and the decision `QuoteTick` and its `OrderBookDepth10`
carry the identical `ts_init` (one venue message), so the quote was delivered
first and the IOC crossed the PREVIOUS snapshot's already-removed 0.04 level.
The adapter agreed with itself at every instant; the driver's recording and
ordering did not.

**The rule.** For a taker order whose limit is the displayed best ask of one
message, `fill_px <= ask` is the only permitted relation; `fill_px < ask` means
the order crossed a book the decision never saw. A replay guards that relation
and raises, records the entry price from the decision instant (the latch), and
applies same-timestamp book updates BEFORE the quote derived from them. A
flattering number is scrutinised harder than a disappointing one — the
mechanism test exists to catch exactly the error that would inflate ROI.

**How to apply.** When a replay or backtest prints negative slippage, a fill
below the decision ask, or a fee of zero on a non-trivial fill, treat it as a
bug until the decision tick and the adjacent depth snapshots have been
reconstructed from the catalog. Never source an "entry" price from a
convenient row (first quote, last quote) when the decision path already
records the real one. Related: [[L-18]], [[L-24]].
