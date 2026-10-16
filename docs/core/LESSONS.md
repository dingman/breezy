# Breezy — Lessons

Binding rules earned from real mistakes on this project. If a proposed approach
violates an active lesson, halt and report rather than proceeding.

Format per entry: Mistake / Prevention / Applied / Last updated. Headers are citation keys and are never renamed. `**Also:**` lists headers absorbed by a merge.

### L-1 — Validate the Nautilus null hypothesis BEFORE proposing to build, not after
**Mistake:** A plan named four components to build without checking whether nautilus-trader 1.231.0 already provided them.
**Prevention:** Cite every increment's null-hypothesis verdict to installed source file:line as `NATIVE CONFIRMED`, `NATIVE EXISTS, DECLINED BECAUSE <cost>`, or `GENUINE GAP` (with the search and a positive control); never accept a bare zero-match under .venv (ripgrep ignores it), so re-run with `grep -r`.
**Applied:** 2026-08-30
**Last updated:** 2026-09-01
**Also:** formerly "L-11 — Claiming a gap where a native exists is the same defect as claiming a native where none does (2026-09-01)"

### L-2 — A native substitution is a UNIT change until proven otherwise (2026-08-30)
**Mistake:** Replacing a max-payout cap with mark-to-market `net_exposure` loosened every cap 20x and shipped as a win.
**Prevention:** Before a framework call replaces a local computation, write `unit before = X; unit after = Y; equal because <reason>`, back each NATIVE-configure verdict with a test that executes the native path, and treat a characterisation test that cannot pass as the signal, not an edit target.
**Applied:** 2026-08-30
**Last updated:** 2026-08-30

### L-3 — A plan whose end state is not the goal state is not a plan (2026-08-31)
**Mistake:** A fully executed plan still left the bot unable to place orders; reviews checked increments, never whether they reach the goal.
**Prevention:** Open each plan with `GOAL STATE: <predicate>` and a `WALK:` checked end to end; plan review must ask what is NOT in the plan and whether its absence stops the goal, treat any undecomposed workstream as the long pole, and verify any cited plan is still live.
**Applied:** 2026-08-31
**Last updated:** 2026-08-31

### L-4 — A fix is a diff against one finding; a document is a set of claims (2026-08-31)
**Mistake:** Fixes closed named findings but left other sites asserting the same fact stale, so criticals rose each round.
**Prevention:** After any revision, grep and verify every site asserting each changed fact and report the sites swept; when findings rise, stop revising and split the document at a domain seam; tag the inference, never the grep result.
**Applied:** 2026-08-31
**Last updated:** 2026-09-01

### L-5 — A state document that outgrows re-verification becomes a source of false claims (2026-08-31)
**Mistake:** PROGRESS.md grew to 1401 lines with closed items and restated evidence, producing false status claims.
**Prevention:** Keep docs/core/PROGRESS.md to OPEN items under 250 lines / 12 KB (`.claude/hooks/progress-size-gate.sh`), delete items on close, link evidence, consolidate rather than raise the budget, and archive superseded history to docs/core/archive/, never delete it.
**Applied:** 2026-08-31
**Last updated:** 2026-08-31

### L-6 — Promoting a shared flag to a kill switch inherits every producer (2026-09-01)
**Mistake:** A boolean read as a fatal exit signal had three writers, and one fired on routine quiet markets.
**Prevention:** Before wiring a boolean to an irreversible action, enumerate every assignment and classify each fatal or not, and split out a fatal class if any writer is routine; fail-closed on an imprecise signal turns noise into an outage.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-7 — Public information has no offer side (2026-09-01)
**Mistake:** A strategy acting on public information submitted zero orders: the winning rung had no asks, because the book had already repriced.
**Prevention:** Ask what the counterparty believes at fill time; if it is public information, measure executable asks before measured certainty, trigger on the physical event rather than publication, and persist the first blocking gate per decision.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-8 — A 0-row read is not a quiet market until the tape is verified (2026-09-01)
**Mistake:** A truncated tape loaded as 0 rows and was read as a quiet market; an HTTP 200 was read as archive coverage (real: 0/168 rows).
**Prevention:** Verify the source before interpreting 0-row, status-code or byte-count results: run `breezy-quote-tape-preflight`, compare `<catalog>/data/` with `<catalog>/live/<instance>/` before calling data missing, and cite row counts for coverage.
**Applied:** 2026-09-01
**Last updated:** 2026-09-02
**Also:** formerly "L-20 — The catalog you query is not the tape you capture (2026-09-02)"

### L-9 — On this venue the near-certain rung is never offered; stop designing lock strategies (2026-09-01)
**Mistake:** Three lock-strategy families failed because the winning rung had no ask at any hour; they assumed a seller of a $1 contract.
**Prevention:** Do not design another near-certain lock-then-buy strategy here; check order AVAILABILITY, then population, then build; remaining edge needs forecast ingestion as Gate 0; gate the pre-event D+1 cheap-open book by its Wilson 95% upper bound against break-even before building for it.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-10 — A brief's vocabulary becomes a subagent's verified fact (2026-09-01)
**Mistake:** A plan presented an unverified Nautilus taxonomy as confirmed and used it to cut scope.
**Prevention:** Verify every fact a brief states (version, API name, taxonomy, coverage span, execution semantic) against source before dispatch, or mark it `UNVERIFIED - confirm before relying`; run the plan peer review before any implementation, even for small increments.
**Applied:** 2026-09-01
**Last updated:** 2026-09-01

### L-12 — Widen an exact-set barrier, never relax it
**Mistake:** Exact-set barriers turned red on legitimate work and tempted loosened assertions; a shared pytest addopts edit changed a pinned filter.
**Prevention:** WIDEN the expected set, never relax the comparison (no `==` to `in`, subset or allowlist); before editing shared config, grep `tests/` for the exact text, change pinned values only in a safety-reviewed item, and remember exact-set membership proves existence, not inertness.
**Applied:** 2026-09-01
**Last updated:** 2026-09-27
**Also:** formerly "L-54 — Shared test config is pinned by containment tests; any edit to it needs a search for its pins first (2026-09-27)"

### L-13 — An extremum statistic is not comparable across different sampling cadences (2026-09-02)
**Mistake:** A sparse hourly source's running max is biased low against dense sources, making a cadence artifact look like a 56-60% edge.
**Prevention:** Before comparing extremum statistics across sources, downsample the dense source to the sparse resolution and recompute; measure what share of the sample a condition excludes, and treat one true of ~99% of samples as no condition.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-14 — A barrier list is DERIVED from "what would refuse this?", never recalled (2026-09-02)
**Mistake:** Barrier lists written from memory missed barriers, and a file was judged out of scope by reading it while the barrier's classifier said in scope.
**Prevention:** Derive barrier lists by running the suite on a deliberately broken change, and decide scope by calling the barrier's own predicate (e.g. `is_venue_touching`) and reporting the measured result; an unmeasurable scope is UNKNOWN; adapt code to the barrier, never narrow it.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02
**Also:** formerly "L-15 — When a barrier's scope is decided by a classifier, RUN the classifier (2026-09-02)"

### L-16 — A raise inside a Nautilus `LiveClock` timer callback is silently discarded (2026-09-02)
**Mistake:** A raise in a Nautilus `LiveClock` timer callback vanished (exit 0, no hook fired).
**Prevention:** A live refusal must write its own operator-visible record at refusal time (latch the fault and write to line-buffered stderr), never rely on a raise, and reproduce which dispatch path applies before accepting any crash claim.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-17 — A field present in every sample you have seen is not thereby REQUIRED (2026-09-02)
**Mistake:** `updatedAt` was required, but the venue omits it on never-modified markets, and one such market blocked discovery for 24 minutes.
**Prevention:** For each required field name the lifecycle state that lacks it and test that state; fall back to creation time for transition timestamps (never `0` or `now()`), widen only the field proven optional, and treat a new population as unproven until observed.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-18 — A counterfactual is a claim about a mechanism you have not run (2026-09-02)
**Mistake:** Docs claimed removing a refusal would 'enable order sends' (it would remove the only denial), and a zero-caller function was cited as a control.
**Prevention:** Before writing that changing X produces Y, name the mechanism carrying Y and check it exists (mark UNVERIFIED otherwise); confirm a cited control has a caller, and that a test's predicate changes, before claiming it will go red.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-19 — Measure a blast radius by SIMULATING the change, not by counting call sites (2026-09-02)
**Mistake:** A hand census of default-reliant sites was off, and `portfolio.equity or 0.0` type-checked while restoring the fabrication.
**Prevention:** Simulate any change to a widely-constructed type's default (monkeypatch it, run the full suite, read every failure), and write out the escape hatch and check it compiles before claiming the type enforces anything.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-21 — A climatological base rate is not the comparator for a market price (2026-09-02)
**Mistake:** A history-only archive probability was taken as a +0.53 edge against a 0.06 ask; the archive ignored the forecast the market prices.
**Prevention:** Treat history-only screens as selectors, never edges; when an archive probability exceeds the ask widely, assume it answers a different question; kill on realized hold rates of selected trials against ask + fee at a pre-named n, and never add conditioning after a miss.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-22 — A safety primitive's exclusion must be unforgeable, not offered (2026-09-03)
**Mistake:** The submit-intent latch was an object plus a separate lock; two arm() calls both returned OPEN.
**Prevention:** Make the lock part of the primitive's only constructor and assert it on every method; reject any brief that lists the lock separately from the guarded object.
**Applied:** 2026-09-03
**Last updated:** 2026-09-03

### L-23 — A configuration snapshot is not the effective runtime; the journal is (2026-09-03)
**Mistake:** A sub-agent read a config field as runtime behaviour, and a missing permit line was read as absence although its handler was never attached at boot.
**Prevention:** Cite the running process's own record (journal, tally, output) for any runtime claim, with a positive control; before claiming absence, name the emitter and its handler and prove a historical occurrence, classify 'never listed' only after a by-identifier probe, else state UNKNOWN.
**Applied:** 2026-09-03
**Last updated:** 2026-09-05
**Also:** formerly "L-30 — A missing log line proves only that nothing was written, not that nothing happened (2026-09-05)"

### L-24 — A fixture that always satisfies an invariant never tests the driver that must supply it (2026-09-04)
**Mistake:** Fixtures pre-satisfied each invariant, hiding the driver's omission until its first real run; an injected seam's production default was never exercised.
**Prevention:** Add a RED test that each invariant still refuses when the driver's input is absent, run at least one test calling each production default un-injected against a cheap real stand-in, and do one real-artefact run before calling it done.
**Applied:** 2026-09-04
**Last updated:** 2026-09-28
**Also:** formerly "L-55 — A test that injects a fake dependency must also run the production default once (2026-09-28)"

### L-25 — A fill better than the displayed ask is a defect signature, not price improvement (2026-09-04)
**Mistake:** A replay showed a fill better than the displayed ask, caused by a stale entry price and out-of-order same-timestamp book updates.
**Prevention:** For a taker limited at the best ask require `fill_px <= ask`; treat `fill_px < ask` or zero fee on a real fill as a bug, take entry from the decision instant, and apply same-timestamp book updates before the quote derived from them.
**Applied:** 2026-09-04
**Last updated:** 2026-09-04

### L-26 — A coordinator session is not a supervisor; a live process launched inside it dies with it (2026-09-04)
**Mistake:** A live node launched with `nohup` inside the coordinator session died with it, with no alert; a setsid relaunch died with the tmux cgroup.
**Prevention:** Start any process that must outlive the session via `systemd-run --user`, verify it under `app.slice` in `/proc/<pid>/cgroup` and with `ps -o pid,sid,pgid`; sessions may only check it; keep the five enablement values memory/shell-only and the two caps in the gitignored operator.env; at session open check `pgrep -f 'breezy-trade$'` and the newest trade log for `Received SIGTERM`.
**Applied:** 2026-09-04
**Last updated:** 2026-09-24

### L-27 — A test that configures a process-global logger can write into the production audit log (2026-09-05)
**Mistake:** A supervisor test suite wrote fake-PID decision lines into the real production audit log.
**Prevention:** Run tests of HOME- or config-derived modules under an autouse fixture redirecting `Path.home()` or injecting `tmp_path`, reset process-global sinks between tests, and guard that the real artefact's size and mtime are unchanged.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-28 — A shipped helper's default arguments are part of the population it measures (2026-09-05)
**Mistake:** A plan reused a shipped counter with its default study-window start, which would have counted six pre-live days and manufactured a KILL.
**Prevention:** Pass every population-selecting argument (dates, stations, catalog, venue) explicitly, share one window across both sides of any ratio, and pin numerator and denominator window equality with a RED test.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-29 — A diagnostics buffer with no production consumer is an unbounded allocation (2026-09-05)
**Mistake:** A per-frame diagnostics list with no production reader grew the trade node to 5.0 GB in six hours.
**Prevention:** Bound every per-message collection by construction (`deque(maxlen=...)`, a counter or flush) with a named production consumer; when RSS grows with message rate, grep the path for `.append(` on `self.*`, test O(1) size, and treat a memory ceiling as containment, not the fix.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-31 — A loop over `catalog.instruments()` runs once per republished definition, not once per instrument (2026-09-06)
**Mistake:** A loop over `catalog.instruments()` ran once per republished definition (210 rows for 60 ids), so one instance never finished.
**Prevention:** Dedupe catalog listings by the key you iterate on before per-row work, pin the selector call count in a test, and measure memory as a retained-object slope (N vs 2N), not RSS over time.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-32 — A backlog row is a claim; search the prior ruling before planning (2026-09-06)
**Mistake:** A HIGH-confidence plan reversed a prior ruling (R-7 item 5) to reclassify empty executions, failing open on a possibly working order.
**Prevention:** Before dispatching a plan that changes an order-state outcome, grep docs/plans and docs/evidence for a converged decision on the same input and cite it as CONFIRMS or CONTRADICTS; a CONTRADICTS halts the row, fail-closed stands until ruled, and a pinned test of a ruled shape is itself a ruling.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-33 — A characterisation item has no RED; demand mutation evidence instead (2026-09-07)
**Mistake:** A no-source-delta item was planned with RED expectations, and one proposed assertion was a tautology, which would have produced a fabricated RED-GREEN.
**Prevention:** Classify each item as CHANGE (RED fails before the delta) or CHARACTERISATION (each new assertion is shown to fail under deliberate perturbation, then restored, returned as `MUTATION_RED_EVIDENCE`).
**Applied:** 2026-09-07
**Last updated:** 2026-09-07

### L-34 — The trial's TRIGGER is pinned; a re-look is a second snapshot (2026-09-09)
**Mistake:** A timer re-evaluation was classed PREREG-COMPATIBLE, but the cached last tick would change which snapshot became the trial.
**Prevention:** Treat a pre-registered trigger as part of the frozen rule: name the datum the rule selects and the datum the change would feed, quote the estimand clause, and classify the change as class (C) if they can differ on any day.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-35 — QuoteTicks cannot observe an empty bid; measure depth from Depth10 (2026-09-09)
**Mistake:** 'The bid side is empty' came from a six-minute sample, and QuoteTicks cannot show an empty bid because one-sided books are refused.
**Prevention:** Never answer 'is there a bid' from the quote tape; use Depth10 with a level walk, weight pooled medians per station-day, state the capture window, and give any exit design a depth walk, spread budget and one-sided-book policy.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-36 — Strict ZERO_FILL is unreachable; a no-fill IOC is AMBIGUOUS until a GET says otherwise (2026-09-10)
**Mistake:** A plan assumed a no-liquidity IOC returns strict ZERO_FILL, but the create response is `{id, executions}` only, so a miss is AMBIGUOUS.
**Prevention:** Never branch on strict ZERO_FILL; a create body of `200` + `id` + `executions == []` stays KIND_AMBIGUOUS (`classify_create_order_outcome` byte-unchanged); resolve with-id intents only via `GET /v1/order/{id}`, fail-closed on any read failure, and keep the in-flight poller disabled; the no-id resolver retires only on complete reads (`RESOLVER_NO_ID_NO_FILL`), and code never invokes `clear_submit_intent`.
**Applied:** 2026-09-10
**Last updated:** 2026-10-03

### L-37 — A swallowed venue-shape error on the create path is a silent-fill hazard (2026-09-11/12)
**Mistake:** A venue fill was refused after the venue added four fields and the error was swallowed, locking the account; a GET resolver retried 3,615 times with no backoff.
**Prevention:** On money-surface shape guards, log the full names-only key tree on refusal, surface swallowed errors into the AMBIGUOUS diagnostic, declare additive drift per surface with evidence (never relax the guard), and back off unbounded venue retries with an age alert.
**Applied:** 2026-09-11
**Last updated:** 2026-09-14

### L-38 — A stop rule whose counter cannot increment is a missing stop, not a running clock (2026-09-12)
**Mistake:** A structural-dead KILL counter read 0 for eight days, so the family traded with its stop unable to fire.
**Prevention:** Before citing a stop as active, show its counter can increment (a day that should count does) and that every family's tally receives it; report a stop that cannot fire as MISSING.
**Applied:** 2026-09-12
**Last updated:** 2026-09-12

### L-39 — Prose that names an operator-reserved control by its env-var name fails the census (2026-09-14)
**Mistake:** An untracked plan named the operator-reserved env vars and failed the census gate.
**Prevention:** Refer to operator-reserved controls only as 'the per-position cap' and 'the daily budget'; before the gate, `grep -c "BREEZY_MAX" <doc>` must print 0.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-40 — A station carries as many positions as it has current rungs; the trial unit is the station-day, with the exact mutual-exclusivity variance (2026-09-14)
**Mistake:** A multi-rung statistic treated sibling rungs as independent, ignoring mutual exclusivity in its variance.
**Prevention:** Derive Var_H0 from the joint distribution (`sum qty_i^2*BE_i(1-BE_i) - 2*sum_{i<j} qty_i*qty_j*BE_i*BE_j`), validate any reused boundary by seeded H0 Monte-Carlo replaying the live look loop including the stop at `I >= I_max`, bound mixed YES+NO days at variance 1.0 not 1/4, and block only the failing scope.
**Applied:** 2026-09-14
**Last updated:** 2026-09-25

### L-41 — A Monte-Carlo null must reproduce the registered H0 exactly; quote noise plus selection manufactures edge (2026-09-14)
**Mistake:** A re-validation selected rungs on the same draw that generated the quotes, inflating crossing rates to 0.03-0.14 and misattributed to winner's curse.
**Prevention:** Before citing a Monte-Carlo crossing rate, confirm it reproduces the registered H0 verbatim (quotes at the cell probability, selection on an independent draw, `E[held - BE | selected] = 0`); label any deviation a sensitivity study with its own variance.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-42 — A test of a store-reading gate must write its fixture through the real writer path (2026-09-14)
**Mistake:** Gates read keys in a convention no writer used, and their tests wrote fixtures in the gate's own convention, so both always passed on production data.
**Prevention:** Create durable state in a reader test through the production writer, never a hand-built key or `consume`; normalise keys in the reader with round-trip tests, and grep new tests for literal `store.set` or `consume(` calls.
**Applied:** 2026-09-14
**Last updated:** 2026-09-14

### L-43 — Two slices that are each green can be jointly broken; gate the integration branch after EVERY merge (2026-09-14)
**Mistake:** Two slices green in their own worktrees broke jointly after merge, and a PREREG amendment cited numbers from the pre-fix code.
**Prevention:** Run the full no-egress gate on the integration branch after every merge, before the next; a worktree gate is not evidence; never cite an artefact not passing on the integration branch; a spawned Python child derives `src` from `breezy.__file__`, never an env var.
**Applied:** 2026-09-14
**Last updated:** 2026-09-25

### L-44 — Logic written for one leg silently mislabels the other; test each leg's terminal state (2026-09-15)
**Mistake:** A shadow monitor's classifier was YES-shaped, so a losing NO position read LOCKED and DEAD was unreachable for NO legs; all fixtures were YES.
**Prevention:** For leg-conditional logic, document both legs in a two-column docstring table, add one test per leg proving its losing terminal state is reachable, and grep tests for a NO-leg fixture (none means RED).
**Applied:** 2026-09-15
**Last updated:** 2026-09-15

### L-45 — A venue limit is per RESOURCE UNIT, not per slug; verify a new subscription type by coverage count on its first boot (2026-09-17)
**Mistake:** Sharding by slug sent two subscription requests per slug; the venue cap is per subscription and shared, so 40 requests were rejected.
**Prevention:** Size sharded resources on the venue's counted unit (subscriptions, not slugs), place MARKET_DATA before optional types and WARN the slugs skipped, verify the first boot by coverage count (`comm -23 <subscribed> <ls order_book_depths>` empty), and ship unmeasured limits opt-in.
**Applied:** 2026-09-17
**Last updated:** 2026-09-17

### L-46 — Disguising the offender is deleting the guard; grep the contract tests before placing a module (2026-09-18)
**Mistake:** A plan placed a module that a contract test forbids; the implementer disguised the host string to pass, and only later reviews caught it.
**Prevention:** Grep `tests/` for each new module path, host or literal and read the matching contract docstrings, revising the plan not the test; reject any value assembled, encoded or aliased to evade a scanner; read every 'deviated' note touching a guard in full.
**Applied:** 2026-09-18
**Last updated:** 2026-09-18

### L-47 — A blanket "verified against installed source" covers nothing; one unverified premise can contradict your own repo's measured fact (2026-09-19)
**Mistake:** A decision record carried a blanket 'verified' assurance over an uncited claim that contradicted a measurement already in the repo.
**Prevention:** Cite file:line for every factual claim about an installed library (a blanket assurance counts for nothing), grep `src/` and `docs/` for prior measurements and STOP on contradiction, show the code path reaches any claimed trap, and strike a refuted premise in place and re-derive the decision.
**Applied:** 2026-09-19
**Last updated:** 2026-09-19

### L-48 — A latch whose only clearing path it blocks is a deadlock, not a safety stop (2026-09-24)
**Mistake:** An AMBIGUOUS intent held the account-wide latch OPEN, and the only clearing path (a running node's resolver) rejected the terminal body, so the node stayed down a day.
**Prevention:** For every blocking latch, name its clearing path and test it end to end with the real stuck shape (venue body verbatim, past-day instrument, boot after the latch was set), and make mapping guards state-aware and field-logging.
**Applied:** 2026-09-24
**Last updated:** 2026-09-24

### L-49 — Low CPU over wall time on a failing unit means a memory ceiling, not a slow job (2026-09-24)
**Mistake:** A unit with `MemoryHigh=4G` against a 90G backlog thrashed in reclaim until timeout; seventeen runs made no progress.
**Prevention:** When CPU/wall < 0.3, check memory.high throttling (`systemctl --user show -p MemoryHigh,MemoryMax,TimeoutStartSec`) before touching timeouts; size ceilings to the current working set; never `read_all()` a one-row-per-message Arrow stream; measure memory as delta RSS in a child process (`ru_maxrss`); keep downstream inputs off one unbounded run.
**Applied:** 2026-09-24
**Last updated:** 2026-09-26

### L-50 — Two writers of one rewrite-in-place file race even when both "append" (2026-09-25)
**Mistake:** Two concurrent ledger writers each read and replaced the file; one record was lost silently while both exited 0.
**Prevention:** Never run two writers of one read-modify-write file concurrently; serialise steps in the brief or hold a lock across the cycle, and read back and assert the exact record set after writes.
**Applied:** 2026-09-25
**Last updated:** 2026-09-25

### L-51 — A worktree shares the venv and the stash stack with production; isolation of files is not isolation of state (2026-09-26)
**Mistake:** A worktree's venv symlinked to production, so `uv sync` there rewrote it; two implementers ran `git stash`, and the stash stack is per-repo.
**Prevention:** From any worktree never run an environment-changing installer (`uv sync`, `uv add`, `uv pip`, `pip install`, `uv run`); use `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src`; never `git stash` (use `git show <sha>:<path>` or a detached scratch worktree); confirm `git stash list` is empty before merging.
**Applied:** 2026-09-26
**Last updated:** 2026-09-26

### L-52 — A corroborating read is evidence only if it can tell the outcomes apart at the time it is read (2026-09-27)
**Mistake:** An empty positions page was treated as zero-fill, though a settled position also leaves the page; a log line via logger.info was invisible in production.
**Prevention:** Before a read can retire, clear or credit anything, state the outcomes it can distinguish and leave the state AMBIGUOUS when it cannot; assert operator-visible lines on the unit's real stream and check the journal after the first live run.
**Applied:** 2026-09-27
**Last updated:** 2026-09-27

### L-53 — A cache cannot fix an input that never completes; one oversized item makes a capped job fail forever (2026-09-27)
**Mistake:** A cache was added to a capped job whose one 8.2 GB item took the whole timeout; an item that never completes is never cached, so the job failed daily.
**Prevention:** Before a caching or incremental fix for a timed-out capped job, confirm the largest single item can complete within the cap alone, fix it with bounded-memory processing if not, and plan SIGKILL as the real stop.
**Applied:** 2026-09-27
**Last updated:** 2026-09-27

### L-56 — A hypothesis picked from a handful of fills cannot be powered by them, and its re-score must use the bot's own band function (2026-10-11)
**Mistake:** A hypothesis chosen from three live fills was re-scored with a half-open band; the real test needed n=1486 against a ceiling of 490.
**Prevention:** Re-score fills only through `bucket_facts_from_instrument_id` (`leg_of_symbol` for `^no`), compute the null fill-count probability, run `recompute_mde` against the station-day ceiling, never count the motivating fills toward n, and check infeasibility across its sensitivity table.
**Applied:** 2026-10-11
**Last updated:** 2026-10-11

### L-57 — A production-default path that a test can reach will write live state the moment its precondition flips (2026-10-11)
**Mistake:** Pinning a producer let an existing guard test reach the production factory on the live host and write a CRITICAL alert.
**Prevention:** A host-path production default must refuse unless inside its exact unit name and not under pytest (`"pytest" in sys.modules`); before unlocking any such path, grep `tests/` for un-injected calls and quarantine spurious artefacts by move.
**Applied:** 2026-10-11
**Last updated:** 2026-10-11
### L-58 — A unit cap is derived from the measured wall of the same job, never guessed (2026-10-16)
**Mistake:** Bench 4 of the S2 replay was launched under a 1,800 s RuntimeMaxSec although the previous bench 4 had taken 3,072 s; systemd killed it and an hour of the launch window was lost.
**Prevention:** Before `systemd-run`, read the last measured wall for that exact job from its log and set RuntimeMaxSec ≥ 1.75× it (window-bounded if needed); a cap below the measured wall is a launch error, never evidence about the job.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

### L-59 — Validate a screen's input distribution on the block before the verdict run (2026-10-16)
**Mistake:** The S-7 clock-offset screen was built on a per-instance max of single-frame offsets; one stale venue transactTime sample (789.8 s) voided the only verdict run after a 2 h preamble and burned a ledger claim, although the block's offsets were available days earlier.
**Prevention:** For every pre-registered screen (S-*), compute its statistic on the frozen block offline (offsets, counts, timestamps only; no fills, rates or labels) before the verdict launch, and treat a trip on that dry run as a design question for the peer loop, not as a run-time surprise.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

### L-60 — A power floor is predicted from the estimator the verdict uses, not from the census headline (2026-10-16)
**Mistake:** S1's census reported n_eff_ub 38.4 on all COVERED station-days, so V0 was not expected; the pre-registered V0 counts only bid-bearing station-days (listed before D-1 12:00Z), which halved the sample to n_eff_gov 18.73 and produced UNDERPOWERED-WAIT after the full run.
**Prevention:** Before launching a verdict run, recompute every floor with the verdict's own estimator and inclusion predicate (here `listed_in_time` ∧ COVERED), record the prediction in the procedure, and treat a predicted WAIT as a reason to extend the block first.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16

Full pre-consolidation text (how-to-apply checks, amendments): docs/core/archive/LESSONS_full_pre-consolidation_2026-10-13.md
