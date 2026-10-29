# Breezy — Lessons

Binding rules earned from real mistakes on this project. If a proposed approach
violates an active lesson, halt and report rather than proceeding.

Format per entry: Mistake / Prevention / Applied / Last updated. Headers are citation keys and are never renamed. `**Also:**` lists headers absorbed by a merge.

### L-1 — Validate the Nautilus null hypothesis BEFORE proposing to build, not after
**Mistake:** Built four components nautilus-trader 1.231.0 already provided; never checked.
**Prevention:** Cite every increment's null-hypothesis verdict to installed source file:line as `NATIVE CONFIRMED`, `NATIVE EXISTS, DECLINED BECAUSE <cost>`, or `GENUINE GAP` (with the search and a positive control); never accept a bare zero-match under .venv (ripgrep ignores it), so re-run with `grep -r`.
**Applied:** 2026-08-30
**Last updated:** 2026-09-01
**Also:** formerly "L-11 — Claiming a gap where a native exists is the same defect as claiming a native where none does (2026-09-01)"

### L-2 — A native substitution is a UNIT change until proven otherwise (2026-08-30)
**Mistake:** `net_exposure` replacing a max-payout cap loosened every cap 20x; shipped.
**Prevention:** Before a framework call replaces a local computation, write `unit before = X; unit after = Y; equal because <reason>`, back each NATIVE-configure verdict with a test that executes the native path, and treat a characterisation test that cannot pass as the signal, not an edit target.
**Applied:** 2026-08-30
**Last updated:** 2026-08-30

### L-3 — A plan whose end state is not the goal state is not a plan (2026-08-31)
**Mistake:** Executed plan could not place orders; reviews checked increments, not the goal.
**Prevention:** Open each plan with `GOAL STATE: <predicate>` and a `WALK:` checked end to end; plan review must ask what is NOT in the plan and whether its absence stops the goal, treat any undecomposed workstream as the long pole, and verify any cited plan is still live.
**Applied:** 2026-08-31
**Last updated:** 2026-08-31

### L-4 — A fix is a diff against one finding; a document is a set of claims (2026-08-31)
**Mistake:** Fixes closed named findings; other sites asserting the same fact stayed stale.
**Prevention:** After any revision, grep and verify every site asserting each changed fact and report the sites swept; when findings rise, stop revising and split the document at a domain seam; tag the inference, never the grep result.
**Applied:** 2026-08-31
**Last updated:** 2026-09-01

### L-6 — Promoting a shared flag to a kill switch inherits every producer (2026-09-01)
**Mistake:** Shared boolean used as fatal exit had three writers; one fired on quiet markets.
**Prevention:** Before wiring a boolean to an irreversible action, enumerate every assignment and classify each fatal or not, and split out a fatal class if any writer is routine; fail-closed on an imprecise signal turns noise into an outage.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-7 — Public information has no offer side (2026-09-01)
**Mistake:** Public-information strategy sent zero orders; the winning rung had no asks.
**Prevention:** Ask what the counterparty believes at fill time; if it is public information, measure executable asks before measured certainty, trigger on the physical event rather than publication, and persist the first blocking gate per decision.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-8 — A 0-row read is not a quiet market until the tape is verified (2026-09-01)
**Mistake:** Truncated tape read as quiet market; HTTP 200 read as coverage (0/168 rows).
**Prevention:** Verify the source before interpreting 0-row, status-code or byte-count results: run `breezy-quote-tape-preflight`, compare `<catalog>/data/` with `<catalog>/live/<instance>/` before calling data missing, and cite row counts for coverage.
**Applied:** 2026-09-01
**Last updated:** 2026-09-02
**Also:** formerly "L-20 — The catalog you query is not the tape you capture (2026-09-02)"

### L-9 — On this venue the near-certain rung is never offered; stop designing lock strategies (2026-09-01)
**Mistake:** Three lock-strategy families failed: the winning rung had no ask at any hour.
**Prevention:** Do not design another near-certain lock-then-buy strategy here; check order AVAILABILITY, then population, then build; remaining edge needs forecast ingestion as Gate 0; gate the pre-event D+1 cheap-open book by its Wilson 95% upper bound against break-even before building for it.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-10 — A brief's vocabulary becomes a subagent's verified fact (2026-09-01)
**Mistake:** An unverified Nautilus taxonomy was presented as confirmed to cut scope.
**Prevention:** Verify every fact a brief states (version, API name, taxonomy, coverage span, execution semantic) against source before dispatch, or mark it `UNVERIFIED - confirm before relying`; run the plan peer review before any implementation, even for small increments. The reverse direction binds too: a returning agent's INFERENCE (2026-10-27: "the selector drops a rung during its own async REPLACE cancel") is a hypothesis until a second agent confirms it from code — never write it into PROGRESS.md as a defect or into a design brief as the premise before that confirmation (the code read showed replay and live reallocate the slot identically; the real gap was elsewhere).
**Applied:** 2026-09-01
**Last updated:** 2026-10-27

### L-12 — Widen an exact-set barrier, never relax it
**Mistake:** Exact-set barriers went red; shared pytest addopts edit changed a pinned filter.
**Prevention:** WIDEN the expected set, never relax the comparison (no `==` to `in`, subset or allowlist); before editing shared config, grep `tests/` for the exact text, change pinned values only in a safety-reviewed item, and remember exact-set membership proves existence, not inertness; a scope guard's EXEMPT/allowlist set changes only in its own reviewed re-pin commit that a dated ruling cites, never in the code commit that needs the widening (10-20: C7 c5f7d3a2 widened EXEMPT from three to four files in the same commit, so the guard could not have caught it).
**Applied:** 2026-09-01
**Last updated:** 2026-10-20
**Also:** formerly "L-54 — Shared test config is pinned by containment tests; any edit to it needs a search for its pins first (2026-09-27)"

### L-13 — An extremum statistic is not comparable across different sampling cadences (2026-09-02)
**Mistake:** Sparse hourly max read low; cadence artifact looked like a 56-60% edge.
**Prevention:** Before comparing extremum statistics across sources, downsample the dense source to the sparse resolution and recompute; measure what share of the sample a condition excludes, and treat one true of ~99% of samples as no condition.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-14 — A barrier list is DERIVED from "what would refuse this?", never recalled (2026-09-02)
**Mistake:** Memory-written barrier lists missed barriers; scope judged without the classifier.
**Prevention:** Derive barrier lists by running the suite on a deliberately broken change, and decide scope by calling the barrier's own predicate (e.g. `is_venue_touching`) and reporting the measured result; an unmeasurable scope is UNKNOWN; adapt code to the barrier, never narrow it.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02
**Also:** formerly "L-15 — When a barrier's scope is decided by a classifier, RUN the classifier (2026-09-02)"

### L-16 — A raise inside a Nautilus `LiveClock` timer callback is silently discarded (2026-09-02)
**Mistake:** A raise in a `LiveClock` timer callback vanished (exit 0, no hook fired).
**Prevention:** A live refusal must write its own operator-visible record at refusal time (latch the fault and write to line-buffered stderr), never rely on a raise, and reproduce which dispatch path applies before accepting any crash claim.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-17 — A field present in every sample you have seen is not thereby REQUIRED (2026-09-02)
**Mistake:** Venue omits required `updatedAt` on never-modified markets; 24 min blocked.
**Prevention:** For each required field name the lifecycle state that lacks it and test that state; fall back to creation time for transition timestamps (never `0` or `now()`), widen only the field proven optional, and treat a new population as unproven until observed.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-18 — A counterfactual is a claim about a mechanism you have not run (2026-09-02)
**Mistake:** Docs said removing a refusal would 'enable order sends' (the only denial).
**Prevention:** Before writing that changing X produces Y, name the mechanism carrying Y and check it exists (mark UNVERIFIED otherwise); confirm a cited control has a caller, and that a test's predicate changes, before claiming it will go red.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-19 — Measure a blast radius by SIMULATING the change, not by counting call sites (2026-09-02)
**Mistake:** Hand census was off; `portfolio.equity or 0.0` type-checked while fabricating.
**Prevention:** Simulate any change to a widely-constructed type's default (monkeypatch it, run the full suite, read every failure), and write out the escape hatch and check it compiles before claiming the type enforces anything.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-21 — A climatological base rate is not the comparator for a market price (2026-09-02)
**Mistake:** History-only archive probability read as a +0.53 edge against a 0.06 ask.
**Prevention:** Treat history-only screens as selectors, never edges; when an archive probability exceeds the ask widely, assume it answers a different question; kill on realized hold rates of selected trials against ask + fee at a pre-named n, and never add conditioning after a miss.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-22 — A safety primitive's exclusion must be unforgeable, not offered (2026-09-03)
**Mistake:** Latch was an object plus a separate lock; two arm() calls both returned OPEN.
**Prevention:** Make the lock part of the primitive's only constructor and assert it on every method; reject any brief that lists the lock separately from the guarded object.
**Applied:** 2026-09-03
**Last updated:** 2026-09-03

### L-23 — A configuration snapshot is not the effective runtime; the journal is (2026-09-03)
**Mistake:** Config read as runtime; missing permit line read as absence, handler never attached.
**Prevention:** Cite the running process's own record (journal, tally, output) for any runtime claim, with a positive control; before claiming absence, name the emitter and its handler and prove a historical occurrence, classify 'never listed' only after a by-identifier probe, else state UNKNOWN.
**Applied:** 2026-09-03
**Last updated:** 2026-09-05
**Also:** formerly "L-30 — A missing log line proves only that nothing was written, not that nothing happened (2026-09-05)"

### L-24 — A fixture that always satisfies an invariant never tests the driver that must supply it (2026-09-04)
**Mistake:** Fixtures pre-satisfied every invariant, hiding the driver's omission.
**Prevention:** Add a RED test that each invariant still refuses when the driver's input is absent, run at least one test calling each production default un-injected against a cheap real stand-in, and do one real-artefact run before calling it done.
**Applied:** 2026-09-04
**Last updated:** 2026-09-28
**Also:** formerly "L-55 — A test that injects a fake dependency must also run the production default once (2026-09-28)"

### L-25 — A fill better than the displayed ask is a defect signature, not price improvement (2026-09-04)
**Mistake:** Fill beat the displayed ask: stale entry price, out-of-order book updates.
**Prevention:** For a taker limited at the best ask require `fill_px <= ask`; treat `fill_px < ask` or zero fee on a real fill as a bug, take entry from the decision instant, and apply same-timestamp book updates before the quote derived from them.
**Applied:** 2026-09-04
**Last updated:** 2026-09-04

### L-26 — A coordinator session is not a supervisor; a live process launched inside it dies with it (2026-09-04)
**Mistake:** `nohup` node in the coordinator session died with it, unalerted.
**Prevention:** Start any process that must outlive the session via `systemd-run --user`, verify it under `app.slice` in `/proc/<pid>/cgroup` and with `ps -o pid,sid,pgid`; sessions may only check it; keep the five enablement values memory/shell-only and the two caps in the gitignored operator.env; at session open check `pgrep -f 'breezy-trade$'` and the newest trade log for `Received SIGTERM`.
**Applied:** 2026-09-04
**Last updated:** 2026-09-24

### L-27 — A test that configures a process-global logger can write into the production audit log (2026-09-05)
**Mistake:** A supervisor test wrote fake-PID lines into the production audit log.
**Prevention:** Run tests of HOME- or config-derived modules under an autouse fixture redirecting `Path.home()` or injecting `tmp_path`, reset process-global sinks between tests, and guard that the real artefact's size and mtime are unchanged.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-28 — A shipped helper's default arguments are part of the population it measures (2026-09-05)
**Mistake:** Default study-window start counted six pre-live days, manufacturing a KILL.
**Prevention:** Pass every population-selecting argument (dates, stations, catalog, venue) explicitly, share one window across both sides of any ratio, and pin numerator and denominator window equality with a RED test.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-29 — A diagnostics buffer with no production consumer is an unbounded allocation (2026-09-05)
**Mistake:** Unread per-frame diagnostics list grew the trade node to 5.0 GB in six hours.
**Prevention:** Bound every per-message collection by construction (`deque(maxlen=...)`, a counter or flush) with a named production consumer; when RSS grows with message rate, grep the path for `.append(` on `self.*`, test O(1) size, and treat a memory ceiling as containment, not the fix.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-31 — A loop over `catalog.instruments()` runs once per republished definition, not once per instrument (2026-09-06)
**Mistake:** `catalog.instruments()` loop ran per republished row (210 rows, 60 ids).
**Prevention:** Dedupe catalog listings by the key you iterate on before per-row work, pin the selector call count in a test, and measure memory as a retained-object slope (N vs 2N), not RSS over time.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-32 — A backlog row is a claim; search the prior ruling before planning (2026-09-06)
**Mistake:** Plan reversed prior ruling R-7 item 5 on empty executions, failing open.
**Prevention:** Before dispatching a plan that changes an order-state outcome, grep docs/plans and docs/evidence for a converged decision on the same input and cite it as CONFIRMS or CONTRADICTS; a CONTRADICTS halts the row, fail-closed stands until ruled, and a pinned test of a ruled shape is itself a ruling.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-33 — A characterisation item has no RED; demand mutation evidence instead (2026-09-07)
**Mistake:** Characterisation item given RED expectations; a tautology fabricated RED-GREEN.
**Prevention:** Classify each item as CHANGE (RED fails before the delta) or CHARACTERISATION (each new assertion is shown to fail under deliberate perturbation, then restored, returned as `MUTATION_RED_EVIDENCE`).
**Applied:** 2026-09-07
**Last updated:** 2026-09-07

### L-34 — The trial's TRIGGER is pinned; a re-look is a second snapshot (2026-09-09)
**Mistake:** Cached last tick changes the trial snapshot; classed PREREG-COMPATIBLE.
**Prevention:** Treat a pre-registered trigger as part of the frozen rule: name the datum the rule selects and the datum the change would feed, quote the estimand clause, and classify the change as class (C) if they can differ on any day.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-35 — QuoteTicks cannot observe an empty bid; measure depth from Depth10 (2026-09-09)
**Mistake:** 'Bid side is empty' read from QuoteTicks, which cannot show an empty bid.
**Prevention:** Never answer 'is there a bid' from the quote tape; use Depth10 with a level walk, weight pooled medians per station-day, state the capture window, and give any exit design a depth walk, spread budget and one-sided-book policy.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-36 — Strict ZERO_FILL is unreachable; a no-fill IOC is AMBIGUOUS until a GET says otherwise (2026-09-10)
**Mistake:** Assumed a no-fill IOC returns strict ZERO_FILL; create body is `{id, executions}`.
**Prevention:** Never branch on strict ZERO_FILL; a create body of `200` + `id` + `executions == []` stays KIND_AMBIGUOUS (`classify_create_order_outcome` byte-unchanged); resolve with-id intents only via `GET /v1/order/{id}`, fail-closed on any read failure, and keep the in-flight poller disabled; the no-id resolver retires only on complete reads (`RESOLVER_NO_ID_NO_FILL`), and code never invokes `clear_submit_intent`.
**Applied:** 2026-09-10
**Last updated:** 2026-10-03

### L-37 — A swallowed venue-shape error on the create path is a silent-fill hazard (2026-09-11/12)
**Mistake:** Swallowed shape error locked the account; GET resolver retried 3,615x unbacked.
**Prevention:** On EVERY venue-shape guard — create, confirm, boot sweep AND the resting poll — log the full names-only key tree on refusal (2026-10-28: `_apply_resting_poll` logged only `exc.__class__.__name__`, so 285 refusals carried no diagnosis while Polymarket.us had added `estimatedAmount`/`estimatedCommission`/`principal` to the Order object — the fourth additive change after balances 09-04/09-19 and order 09-11); treat additive venue fields as a recurring event whose standing response is the declared-but-unread allowlist plus a value-free evidence note, never a relaxed guard; surface swallowed errors into the AMBIGUOUS diagnostic; back off unbounded venue retries with an age alert.
**Applied:** 2026-09-11
**Last updated:** 2026-10-28

### L-38 — A stop rule whose counter cannot increment is a missing stop, not a running clock (2026-09-12)
**Mistake:** KILL counter read 0 for eight days; the stop could not fire.
**Prevention:** Before citing a stop as active, show its counter can increment (a day that should count does) and that every family's tally receives it; report a stop that cannot fire as MISSING.
**Applied:** 2026-09-12
**Last updated:** 2026-09-12

### L-39 — Prose that names an operator-reserved control by its env-var name fails the census (2026-09-14)
**Mistake:** Untracked plan named operator-reserved env vars; failed the census gate.
**Prevention:** Refer to operator-reserved controls only as 'the per-position cap' and 'the daily budget'; before the gate, `grep -c "BREEZY_MAX" <doc>` must print 0.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-40 — A station carries as many positions as it has current rungs; the trial unit is the station-day, with the exact mutual-exclusivity variance (2026-09-14)
**Mistake:** Sibling rungs treated as independent, ignoring mutual exclusivity.
**Prevention:** Derive Var_H0 from the joint distribution (`sum qty_i^2*BE_i(1-BE_i) - 2*sum_{i<j} qty_i*qty_j*BE_i*BE_j`), validate any reused boundary by seeded H0 Monte-Carlo replaying the live look loop including the stop at `I >= I_max`, bound mixed YES+NO days at variance 1.0 not 1/4, and block only the failing scope.
**Applied:** 2026-09-14
**Last updated:** 2026-09-25

### L-41 — A Monte-Carlo null must reproduce the registered H0 exactly; quote noise plus selection manufactures edge (2026-09-14)
**Mistake:** Selection on the quote-generating draw inflated crossing rates to 0.03-0.14.
**Prevention:** Before citing a Monte-Carlo crossing rate, confirm it reproduces the registered H0 verbatim (quotes at the cell probability, selection on an independent draw, `E[held - BE | selected] = 0`); label any deviation a sensitivity study with its own variance.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-42 — A test of a store-reading gate must write its fixture through the real writer path (2026-09-14)
**Mistake:** Gates read keys no writer used; fixtures used the gate's own convention.
**Prevention:** Create durable state in a reader test through the production writer, never a hand-built key or `consume`; normalise keys in the reader with round-trip tests, and grep new tests for literal `store.set` or `consume(` calls.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-43 — Two slices that are each green can be jointly broken; gate the integration branch after EVERY merge (2026-09-14)
**Mistake:** Slices green alone broke jointly after merge; PREREG amendment cited pre-fix numbers.
**Prevention:** Run the full no-egress gate on the integration branch after every merge, before the next; a worktree gate is not evidence; never cite an artefact not passing on the integration branch; a spawned Python child derives `src` from `breezy.__file__`, never an env var.
**Applied:** 2026-09-14
**Last updated:** 2026-09-25

### L-44 — Logic written for one leg silently mislabels the other; test each leg's terminal state (2026-09-15)
**Mistake:** YES-shaped classifier: DEAD unreachable for NO legs; all fixtures were YES.
**Prevention:** For leg-conditional logic, document both legs in a two-column docstring table, add one test per leg proving its losing terminal state is reachable, and grep tests for a NO-leg fixture (none means RED).
**Applied:** 2026-09-15
**Last updated:** 2026-09-15

### L-45 — A venue limit is per RESOURCE UNIT, not per slug; verify a new subscription type by coverage count on its first boot (2026-09-17)
**Mistake:** Sharding by slug sent two requests per slug; shared venue cap rejected 40.
**Prevention:** Size sharded resources on the venue's counted unit (subscriptions, not slugs), place MARKET_DATA before optional types and WARN the slugs skipped, verify the first boot by coverage count (`comm -23 <subscribed> <ls order_book_depths>` empty), and ship unmeasured limits opt-in.
**Applied:** 2026-09-17
**Last updated:** 2026-09-17

### L-46 — Disguising the offender is deleting the guard; grep the contract tests before placing a module (2026-09-18)
**Mistake:** Plan placed a module a contract test forbids; host string disguised to pass.
**Prevention:** Grep `tests/` for each new module path, host or literal and read the matching contract docstrings, revising the plan not the test; reject any value assembled, encoded or aliased to evade a scanner; read every 'deviated' note touching a guard in full.
**Applied:** 2026-09-18
**Last updated:** 2026-09-18

### L-47 — A blanket "verified against installed source" covers nothing; one unverified premise can contradict your own repo's measured fact (2026-09-19)
**Mistake:** Blanket 'verified' covered an uncited claim contradicting a repo measurement.
**Prevention:** Cite file:line for every factual claim about an installed library (a blanket assurance counts for nothing), grep `src/` and `docs/` for prior measurements and STOP on contradiction, show the code path reaches any claimed trap, and strike a refuted premise in place and re-derive the decision. The same rule binds an ARM checklist: every pre-ARM gate item carries its MEASURED value in the ARM commit message (2026-10-27: the P4 gate "replay with `unreadable == 0`" was never met — `unreadable=1` on every producer run since install — and no waiver was recorded; a ticked box with no number is a blanket assurance).
**Applied:** 2026-09-19
**Last updated:** 2026-10-27

### L-48 — A latch whose only clearing path it blocks is a deadlock, not a safety stop (2026-09-24)
**Mistake:** AMBIGUOUS intent held the latch OPEN; its clearing path rejected the body.
**Prevention:** For every blocking latch, name its clearing path and test it end to end with the real stuck shape (venue body verbatim, past-day instrument, boot after the latch was set), and make mapping guards state-aware and field-logging. The clearing path must not depend on the triggering object staying alive: 2026-10-28 `resting_query_unreadable` clears only on a readable poll of the SAME order id, the three unreadable rests expired and left `resting_index`, so the latch was unreachable for the remaining 6.5 h of the window while the node looked healthy — add the sequence "latch → terminal event on the triggering order → recovery evidence" to every latch's test list.
**Applied:** 2026-09-24
**Last updated:** 2026-10-28

### L-49 — Low CPU over wall time on a failing unit means a memory ceiling, not a slow job (2026-09-24)
**Mistake:** `MemoryHigh=4G` on a 90G backlog thrashed in reclaim until timeout.
**Prevention:** When CPU/wall < 0.3, check memory.high throttling (`systemctl --user show -p MemoryHigh,MemoryMax,TimeoutStartSec`) before touching timeouts; size ceilings to the current working set; never `read_all()` a one-row-per-message Arrow stream; measure memory as delta RSS in a child process (`ru_maxrss`); keep downstream inputs off one unbounded run.
**Applied:** 2026-09-24
**Last updated:** 2026-09-26

### L-50 — Two writers of one rewrite-in-place file race even when both "append" (2026-09-25)
**Mistake:** Two concurrent read-modify-replace writers lost a record; both exited 0.
**Prevention:** Never run two writers of one read-modify-write file concurrently; serialise steps in the brief or hold a lock across the cycle, and read back and assert the exact record set after writes.
**Applied:** 2026-09-25
**Last updated:** 2026-09-25

### L-51 — A worktree shares the venv and the stash stack with production; isolation of files is not isolation of state (2026-09-26)
**Mistake:** Worktree venv symlinked to production (`uv sync` rewrote it); `git stash` used.
**Prevention:** From any worktree never run an environment-changing installer (`uv sync`, `uv add`, `uv pip`, `pip install`, `uv run`); use `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src`; never `git stash` (use `git show <sha>:<path>` or a detached scratch worktree); confirm `git stash list` is empty before merging.
**Applied:** 2026-09-26
**Last updated:** 2026-09-26

### L-52 — A corroborating read is evidence only if it can tell the outcomes apart at the time it is read (2026-09-27)
**Mistake:** Empty positions page read as zero-fill; settled positions also leave it.
**Prevention:** Before a read can retire, clear or credit anything, state the outcomes it can distinguish and leave the state AMBIGUOUS when it cannot; assert operator-visible lines on the unit's real stream and check the journal after the first live run.
**Applied:** 2026-09-27
**Last updated:** 2026-09-27

### L-53 — A cache cannot fix an input that never completes; one oversized item makes a capped job fail forever (2026-09-27)
**Mistake:** Cache added to a capped job whose one 8.2 GB item never fit the timeout.
**Prevention:** Before a caching or incremental fix for a timed-out capped job, confirm the largest single item can complete within the cap alone, fix it with bounded-memory processing if not, and plan SIGKILL as the real stop.
**Applied:** 2026-09-27
**Last updated:** 2026-09-27

### L-56 — A hypothesis picked from a handful of fills cannot be powered by them, and its re-score must use the bot's own band function (2026-10-11)
**Mistake:** Hypothesis from three fills re-scored with a half-open band; n=1486 needed.
**Prevention:** Re-score fills only through `bucket_facts_from_instrument_id` (`leg_of_symbol` for `^no`), compute the null fill-count probability, run `recompute_mde` against the station-day ceiling, never count the motivating fills toward n, and check infeasibility across its sensitivity table.
**Applied:** 2026-10-11
**Last updated:** 2026-10-11

### L-58 — A unit cap is derived from the measured wall of the same job, never guessed (2026-10-16)
**Mistake:** S2 bench 4 ran under 1,800 s RuntimeMaxSec; prior run took 3,072 s.
**Prevention:** Before `systemd-run`, read the last measured wall for that exact job from its log and set RuntimeMaxSec ≥ 1.75× it (window-bounded if needed); a cap below the measured wall is a launch error, never evidence about the job.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

### L-59 — Validate a screen's input distribution on the block before the verdict run (2026-10-16)
**Mistake:** One stale 789.8 s transactTime sample set the S-7 offset max; voided the run.
**Prevention:** For every pre-registered screen (S-*), compute its statistic on the frozen block offline (offsets, counts, timestamps only; no fills, rates or labels) before the verdict launch, and treat a trip on that dry run as a design question for the peer loop, not as a run-time surprise.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

### L-60 — A power floor is predicted from the estimator the verdict uses, not from the census headline (2026-10-16)
**Mistake:** S1 census (n_eff_ub 38.4, all COVERED) ignored V0's bid-bearing filter.
**Prevention:** Before launching a verdict run, recompute every floor with the verdict's own estimator and inclusion predicate (here `listed_in_time` ∧ COVERED), record the prediction in the procedure, and treat a predicted WAIT as a reason to extend the block first.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

### L-62 — A Grok --prompt-file brief is task text only; flags in it are passed as one argv token (2026-10-20)
**Mistake:** Brief began "--background --cwd …"; grok exited 2 in 27 ms and the apostrophe truncated the prompt.
**Prevention:** Grok --prompt-file briefs: task text only, no flag line; bridge flags (--background --write --cwd --prompt-file) on the run command; `grep -c "'" brief` must print 0 before dispatch; the poll agent checks `runs <id>` once at +60 s and reports failed runs immediately.
**Applied:** 2026-10-20
**Last updated:** 2026-10-20

Full pre-consolidation text (how-to-apply checks, amendments): docs/core/archive/LESSONS_full_pre-consolidation_2026-10-13.md

Archived 2026-10-20 (mechanised): L-5, L-57, L-61 → docs/core/archive/LESSONS-archive-2026-10-20.md

### L-63 — A planned reboot stops the recorder first; an unclean one condemns the open instance (2026-10-20)
**Mistake:** The 2026-10-19 02:34Z host reboot killed `breezy-quote-tape.service` mid-write; six files in streams the census never reads were 8 bytes short, the classifier condemned the whole instance 70261a13 (10-18 09:00Z → 10-19), and the S2 trigger lost two covered dates (E 11-04 → 11-06).
**Prevention:** Before any planned reboot run `systemctl --user stop breezy-quote-tape.service` and wait for the `Stopped` line (`deploy/systemd/README.md:89-102`); after any unclean reboot run the census on the open instance at once and accept the loss — never salvage or reclassify under a pre-registered classifier after seeing counts.
**Applied:** 2026-10-20
**Last updated:** 2026-10-20

### L-64 — A live test premised on a replay fill rate pre-registers an opportunity monitor beside it (2026-10-27)
**Mistake:** P4 was armed on an in-sample 0.70 fills/day; that rate was carried by a 10-09..10-13 thin-queue burst (3.5 h/station-day vs 1.36 before it), the thin-queue opportunity fell ≈3× right after the selection window closed, and the "market disagrees with model" rungs that produced all 17 in-sample fills were 0/day from 10-17 on. Three live windows produced 0 fills and the only diagnosis available was post hoc.
**Prevention:** Before arming any family whose evidence depends on being filled, pre-register and schedule (daily, read-only, from the tape) the market-opportunity statistic the fills came from — here thin-queue rest-hours per station-day and the count of disagree rungs — with its in-sample level and a STOP/INCONCLUSIVE threshold written beside the fill-rate rate check; a drop in the monitor rules the test inconclusive-by-regime on the day it happens, not at day 21.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-65 — A replay tape never holds the strategy's own orders; a live book does (2026-10-27)
**Mistake:** The maker priced live from a Depth10 frame that contained its own resting NO bid (a YES ask at `100 − bid`); `selector.py` did not exclude it, so when our bid was best it ratcheted one tick per frame toward the cap, REPLACEd, and lost the slot — on the only thin-queue rung seen live in three days. The Stage 0 replay never did this because the pre-arm tape had no orders of ours, and its fill pass also modelled no order-count budget, latches or cancel-ack latency (live keeps 9 of 17 replay fills under those alone).
**Prevention:** Before promoting a family from replay to live, (a) make the parity fixture echo the strategy's own open orders into every frame it prices from and assert live == replay posts under that echo; (b) list every venue limit the exec path enforces (order-count budget, intent latch, AMBIGUOUS latch, cancel-ack wait, GTD cap) and either model each in the replay or post-filter the replay's fills under it and report the survivors as the live expectation; (c) treat post-arm tape as self-contaminated for any later replay of that family.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-66 — The serial gate without an in-tree basetemp lands on the 16 GB tmpfs and fails DiskLow (2026-10-27)
**Mistake:** `scripts/ci/run_tests_no_egress.sh` run with no `--basetemp` put pytest's tmp under `/tmp` (tmpfs, 4.8 GB free); the Stage 0 driver preflight requires 10 GB free on the tmp filesystem, so 97 Stage 0 tests failed `DiskLow` and the only real finding (a stale mypy ceiling) was buried under them for 32 minutes.
**Prevention:** Always invoke the serial gate as `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/<name>` and `rm -rf` that directory after reading `GATE_EXIT`; when a gate fails with ≥50 failures, group the `E ` lines by message before reading any single traceback — one environmental cause looks like a hundred bugs.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-67 — Probe the delegation route before the first dispatch, not after (2026-10-28)
**Mistake:** The cycle opened with three Claude sub-agent dispatches on the assumption that Grok was still 402-exhausted (true the previous day); `~/.claude/bin/grok-check.sh` run afterwards returned 0, so the first stage ran on the third-choice route while the first-choice route was available.
**Prevention:** The first command of every cycle is `~/.claude/bin/grok-check.sh` (0 = usable, 2 = 402) followed by the one-line Codex probe; route the whole cycle from those two results and state the route in the cycle record before any dispatch. A yesterday's-state assumption about an external route is a premise to verify, never a fact.
**Applied:** 2026-10-28
**Last updated:** 2026-10-28

### L-68 — Nautilus LiveClock callbacks run off the kernel thread; hop before touching thread-confined state (2026-10-24, recorded 2026-10-28)
**Mistake:** On P4 arm day the maker's 30 s `MAKER-POLL` timer read the FQ halt veto from `SqliteStateStore` inside the LiveClock callback; the store's `_check_thread` raised off-thread, the veto failed closed (`fq_halt_veto_unreadable`) and every rest was cancelled each cycle (39 submitted, 81 denied, 0 fills) until the node was stopped. TestClock unit tests never see it. The rule lived only in auto-memory, so 10-28 reviewers could not cite it.
**Prevention:** Every strategy clock callback that touches thread-confined state (state store, exec-client latches, caches) goes through the `_on_clock` wrapper that hops onto the kernel loop (`loop.call_soon_threadsafe`, loop captured in `on_start`; fix ed888605); any review of a new timer or of exec-client state mutation names the thread it runs on, and the first live minutes after a new timer are checked for thread errors.
**Applied:** 2026-10-24
**Last updated:** 2026-10-28

### L-69 — The bot's venue account is shared with a human; any manual position latches the node by design (2026-10-28)
**Mistake:** After a gated, reviewed fix was relaunched at 23:45Z the node denied every submit: the account held a $5 NBA parlay bought through the venue UI six minutes earlier (`crossd-…`, a combo market with no public Market object), and the exec client's fail-closed guard on positions it cannot map or net refused to trade. The whole relaunched window was lost, the fix could not be confirmed live, and the same account had NBA prop fills on 10-20 that nobody had connected to the bot's readiness.
**Prevention:** Before every node launch or relaunch run the read-only positions probe (`GET /v1/portfolio/positions` via the shipped client) and treat any slug outside `tc-temp-*` as a launch blocker to SURFACE to the operator, never to work around: do not sell, hide or allowlist the position and do not weaken the guard. Operator ruling 2026-10-29: the operator DOES trade manually in this account and the bot must ignore everything the operator does there — positions and open orders outside Breezy's slug grammar (`tc-temp-*`; e.g. `crossd-*`, `astatc-*`) are FOREIGN: logged once, never netted, sold, hidden or allowlisted, and never a reason to refuse; a `tc-temp-*` position without a loaded instrument remains a refusal. Until EXEC-FOREIGN-POS ships (PROGRESS.md), `instrument_absent>0` on a foreign slug at boot is expected, not an incident, and is never worked around by hand.
**Applied:** 2026-10-28; EXEC-FOREIGN-POS Stage A (positions) LIVE at the 16:50Z boot 10-29 — the pre-registered prediction `instrument_absent=0 foreign=1 refusals=0` matched the boot log token for token and the latch cleared by classification, not by a weakened guard (`docs/evidence/P4_LIVE_READ_2026-10-29.md`). Stage B (open orders) pending; until it ships a manual DAY order still latches the boot sweep.
**Last updated:** 2026-10-29

### L-70 — A cycle that waits on an external event must arm its own re-entry (2026-10-29)
**Mistake:** Two cycles (10-27, 10-28) ended correctly on "external event pending" but nothing re-entered the loop: the bot's systemd timers run the bot, not the orchestrator, and no session cron, wakeup or host timer existed. The loop only resumed when the operator re-pasted the brief. In the same cycles the main session issued 109 Bash calls and 26 Monitors itself, which drove two auto-compactions (≈386k and ≈362k tokens) whose summaries then misreported state.
**Prevention:** Before ending any cycle on a pending event, schedule the re-entry at the event time (CronCreate in-session, or the host timer), verify it with CronList/`systemctl --user list-timers`, and write the wake time in PROGRESS.md; a cycle end without a scheduled resumption or an explicit operator stop is a defect (CLAUDE.md "Cycle Lifecycle"). Inside a cycle, delegate gate runs, log reads and watches as single units with ≤15-line returns; main never runs Monitor or diagnostic Bash beyond one lookup.
**Applied:** 2026-10-29
**Last updated:** 2026-10-29
