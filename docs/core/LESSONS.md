# Breezy — Lessons

Binding rules earned from real mistakes on this project. If a proposed approach
violates an active lesson, halt and report rather than proceeding.

Format per entry: Mistake / Prevention / Applied / Last updated. Headers are citation keys and are never renamed. Absorbed L-numbers are named in the survivor's heading and mapped in the Absorbed index at the end.

### L-1 — Validate the Nautilus null hypothesis BEFORE proposing to build, not after (absorbs L-11, L-73, L-74)
**Mistake:** Four components were built that nautilus-trader already provided; blind-tool zero counts were read as absence.
**Prevention:** Cite each null-hypothesis verdict to installed source file:line as `NATIVE CONFIRMED`, `NATIVE EXISTS, DECLINED BECAUSE <cost>` or `GENUINE GAP`, with search and positive control. Re-run .venv zeros with `grep -r`; count `\[ERROR\]` and ruling files via `ls -la` (never Glob); suspect the tool when agents agree against a shell count; open symlinked dirs by path, reporting files read and symlinks followed separately.
**Applied:** 2026-08-30
**Last updated:** 2026-11-02

### L-2 — A native substitution is a UNIT change until proven otherwise (2026-08-30)
**Mistake:** A native call replaced a max-payout cap and loosened every cap 20x.
**Prevention:** Before a framework call replaces a local computation, write `unit before = X; unit after = Y; equal because <reason>`; back each NATIVE-configure verdict with a test that runs the native path. A characterisation test that cannot pass is the signal, not an edit target.
**Applied:** 2026-08-30
**Last updated:** 2026-08-30

### L-3 — A plan whose end state is not the goal state is not a plan (2026-08-31)
**Mistake:** A plan could not place orders; reviews checked increments, not the goal.
**Prevention:** Open each plan with `GOAL STATE: <predicate>` and a `WALK:` checked end to end. Plan review asks what the plan omits and whether that stops the goal, treats any undecomposed workstream as the long pole, and verifies cited plans are live.
**Applied:** 2026-08-31
**Last updated:** 2026-08-31

### L-4 — A fix is a diff against one finding; a document is a set of claims (2026-08-31)
**Mistake:** Fixes closed named findings while other sites asserting the same fact stayed stale.
**Prevention:** After any revision, grep and verify every site asserting each changed fact, and report the sites swept. When findings rise, stop revising and split at a domain seam. Tag the inference, never the grep result.
**Applied:** 2026-08-31
**Last updated:** 2026-09-01

### L-6 — Promoting a shared flag to a kill switch inherits every producer (2026-09-01) (absorbs L-38)
**Mistake:** A shared fatal boolean had three writers, one firing on quiet markets; a KILL counter read 0 for eight days.
**Prevention:** Before wiring a boolean to an irreversible action, enumerate every assignment, classify each fatal or not, and split out a fatal class if any writer is routine. Before citing a stop as active, show its counter can increment and every family's tally receives it; a stop that cannot fire is MISSING.
**Applied:** 2026-09-01
**Last updated:** 2026-11-02

### L-8 — A 0-row read is not a quiet market until the tape is verified (2026-09-01) (absorbs L-20, L-23, L-30)
**Mistake:** A truncated tape was read as a quiet market, HTTP 200 as coverage, and a missing log line as absence.
**Prevention:** Verify the source before reading a 0-row, status-code, byte-count or log-absence result: run `breezy-quote-tape-preflight`; compare `<catalog>/data/` with `<catalog>/live/<instance>/`; cite row counts; for runtime claims cite the process's own record with a positive control; before claiming absence, name the emitter and handler and prove a historical occurrence. Classify 'never listed' only after a by-identifier probe (else UNKNOWN).
**Applied:** 2026-09-01
**Last updated:** 2026-11-02

### L-9 — On this venue the near-certain rung is never offered; stop designing lock strategies (2026-09-01) (absorbs L-7)
**Mistake:** Three lock-strategy families failed because the winning rung had no ask.
**Prevention:** Do not design another near-certain lock-then-buy strategy here. Check order AVAILABILITY and executable asks before measured certainty, population, then build; ask what the counterparty believes at fill time; trigger on the physical event, not publication; persist the first blocking gate per decision; gate the pre-event D+1 cheap-open book by its Wilson 95% upper bound against break-even; treat remaining edge as forecast ingestion (Gate 0).
**Applied:** 2026-09-01
**Last updated:** 2026-11-02

### L-10 — A brief's vocabulary becomes a subagent's verified fact (2026-09-01) (absorbs L-47)
**Mistake:** An unverified Nautilus taxonomy in a brief was presented as confirmed, and a blanket 'verified' covered a refuted claim.
**Prevention:** Verify and cite file:line against installed source for every fact a brief states (version, API name, taxonomy, coverage span, execution semantic), or mark it `UNVERIFIED - confirm before relying`. Grep `src/` and `docs/` for prior measurements and STOP on contradiction; show the code path reaches any claimed trap; strike a refuted premise and re-derive. Carry each pre-ARM gate item's MEASURED value in the ARM commit message; run plan peer review before implementation. A returning agent's inference is a hypothesis until a second agent confirms it from code.
**Applied:** 2026-09-01
**Last updated:** 2026-11-02

### L-12 — Widen an exact-set barrier, never relax it (absorbs L-46, L-54)
**Mistake:** An exact-set barrier went red after a shared pytest config edit changed a pinned filter; a module placement disguised a host string to pass a contract test.
**Prevention:** WIDEN the expected set, never relax the comparison (no `==` to `in`, subset or allowlist). Before placing a module or editing shared config, grep `tests/` for each module path, host or exact text; read the matching contract docstrings and every 'deviated' note touching a guard in full; revise the plan, not the test. Change pinned values or a scope guard's EXEMPT/allowlist only in its own safety-reviewed re-pin item that a dated ruling cites, never in the code commit that needs the widening. Reject any value assembled, encoded or aliased to evade a scanner. Exact-set membership proves existence, not inertness.
**Applied:** 2026-09-01
**Last updated:** 2026-11-02

### L-13 — An extremum statistic is not comparable across different sampling cadences (2026-09-02)
**Mistake:** A sparse hourly max read low, and the cadence artifact looked like a 56-60% edge.
**Prevention:** Downsample the dense source to the sparse resolution, then recompute, before comparing extremum statistics. Measure the share of the sample a condition excludes; a condition true of ~99% of samples is no condition.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-14 — A barrier list is DERIVED from "what would refuse this?", never recalled (2026-09-02) (absorbs L-15, L-19)
**Mistake:** Memory-written barrier lists missed barriers, and a hand call-site census was off while a fabricating `or 0.0` default type-checked.
**Prevention:** Derive barrier lists by running the suite on a deliberately broken change; decide scope by calling the barrier's own predicate and reporting the measured result; treat an unmeasurable scope as UNKNOWN; adapt code to the barrier, never narrow it. Measure blast radius by SIMULATING the change: monkeypatch a widely-constructed type's default, run the full suite, read every failure. Write out the escape hatch and check it compiles before claiming the type enforces anything.
**Applied:** 2026-09-02
**Last updated:** 2026-11-02

### L-16 — A raise inside a Nautilus `LiveClock` timer callback is silently discarded (2026-09-02) (absorbs L-68)
**Mistake:** A raise in a `LiveClock` timer callback vanished with exit 0; a timer read thread-confined state off the kernel thread and cancelled every rest.
**Prevention:** A live refusal writes its own operator-visible record at refusal time (latched fault, line-buffered stderr), never relies on a raise, and reproduces the dispatch path before accepting any crash claim. Route every clock callback touching thread-confined state (state store, exec-client latches, caches) through the `_on_clock` wrapper that hops to the kernel loop via `loop.call_soon_threadsafe` (loop captured in `on_start`); name the thread of any new timer or exec-client mutation; check the first live minutes for thread errors.
**Applied:** 2026-09-02
**Last updated:** 2026-11-02

### L-17 — A field present in every sample you have seen is not thereby REQUIRED (2026-09-02)
**Mistake:** A venue omitted a required `updatedAt` on never-modified markets, blocking 24 minutes.
**Prevention:** For each required field, name the lifecycle state that lacks it and test that state. Fall back to creation time for transition timestamps (never `0` or `now()`); widen only a field proven optional; treat a new population as unproven until observed.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-18 — A counterfactual is a claim about a mechanism you have not run (2026-09-02)
**Mistake:** Docs said removing a refusal would enable order sends, which was not the only denial.
**Prevention:** Before writing that changing X produces Y, name the mechanism carrying Y and check it exists (else mark UNVERIFIED). Confirm a cited control has a caller and that a test's predicate changes before claiming it will go red.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-21 — A climatological base rate is not the comparator for a market price (2026-09-02)
**Mistake:** A history-only archive probability was read as a +0.53 edge against a 0.06 ask.
**Prevention:** Treat history-only screens as selectors, never edges; when an archive probability exceeds the ask widely, assume it answers a different question. Kill on realized hold rates of selected trials against ask plus fee at a pre-named n; never add conditioning after a miss.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02

### L-22 — A safety primitive's exclusion must be unforgeable, not offered (2026-09-03)
**Mistake:** A latch was an object plus a separate lock, so two arm() calls both returned OPEN.
**Prevention:** Make the lock part of the primitive's only constructor and assert it on every method; reject any brief that lists the lock separately from the guarded object.
**Applied:** 2026-09-03
**Last updated:** 2026-09-03

### L-24 — A fixture that always satisfies an invariant never tests the driver that must supply it (2026-09-04) (absorbs L-42, L-55)
**Mistake:** Fixtures pre-satisfied every invariant, and reader tests used hand-built store keys no production writer used.
**Prevention:** Add a RED test that each invariant still refuses when the driver's input is absent. Run each production default un-injected at least once against a cheap real stand-in. Create durable state in reader tests only through the production writer (grep new tests for literal `store.set` or `consume(`), with round-trip tests for key normalisation in the reader. Do one real-artefact run before calling it done.
**Applied:** 2026-09-04
**Last updated:** 2026-11-02

### L-25 — A fill better than the displayed ask is a defect signature, not price improvement (2026-09-04)
**Mistake:** A fill beat the displayed ask because of a stale entry price and out-of-order book updates.
**Prevention:** For a taker limited at the best ask, require `fill_px <= ask`; treat `fill_px < ask` or zero fee on a real fill as a bug. Take entry from the decision instant, and apply same-timestamp book updates before the quote derived from them.
**Applied:** 2026-09-04
**Last updated:** 2026-09-04

### L-26 — A coordinator session is not a supervisor; a live process launched inside it dies with it (2026-09-04)
**Mistake:** A `nohup` node in the coordinator session died with it, unalerted.
**Prevention:** Start any process that must outlive the session via `systemd-run --user`; verify it under `app.slice` in `/proc/<pid>/cgroup` and with `ps -o pid,sid,pgid`; sessions only check it. Keep the five enablement values memory/shell-only and the two caps in the gitignored operator.env. At session open, check `pgrep -f 'breezy-trade$'` and the newest trade log for `Received SIGTERM`.
**Applied:** 2026-09-04
**Last updated:** 2026-09-24

### L-27 — A test that configures a process-global logger can write into the production audit log (2026-09-05)
**Mistake:** A supervisor test wrote fake-PID lines into the production audit log.
**Prevention:** Run tests of HOME- or config-derived modules under an autouse fixture that redirects `Path.home()` or injects `tmp_path`; reset process-global sinks between tests; guard that the real artefact's size and mtime are unchanged.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-28 — A shipped helper's default arguments are part of the population it measures (2026-09-05)
**Mistake:** A default study-window start counted six pre-live days, manufacturing a KILL.
**Prevention:** Pass every population-selecting argument (dates, stations, catalog, venue) explicitly; share one window across both sides of any ratio; pin numerator and denominator window equality with a RED test.
**Applied:** 2026-09-05
**Last updated:** 2026-09-05

### L-29 — A diagnostics buffer with no production consumer is an unbounded allocation (2026-09-05) (absorbs L-49)
**Mistake:** An unread per-frame diagnostics list grew the trade node to 5.0 GB in six hours; a `MemoryHigh=4G` cap on a 90G backlog thrashed until timeout.
**Prevention:** Bound every per-message collection by construction (`deque(maxlen=...)`, a counter or flush) with a named production consumer; when RSS grows with message rate, grep `self.*` for `.append(`, test O(1) size, and treat a memory ceiling as containment, not the fix. If CPU/wall is below 0.3 on a failing unit, check memory.high throttling (`systemctl --user show -p MemoryHigh,MemoryMax,TimeoutStartSec`) before touching timeouts; size ceilings to the working set; never `read_all()` a one-row-per-message Arrow stream; measure memory as delta RSS in a child process (`ru_maxrss`); keep downstream inputs off one unbounded run.
**Applied:** 2026-09-05
**Last updated:** 2026-11-02

### L-31 — A loop over `catalog.instruments()` runs once per republished definition, not once per instrument (2026-09-06)
**Mistake:** A `catalog.instruments()` loop ran once per republished row.
**Prevention:** Dedupe catalog listings by the key you iterate on before per-row work; pin the selector call count in a test; measure memory as a retained-object slope (N vs 2N), not RSS over time.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-32 — A backlog row is a claim; search the prior ruling before planning (2026-09-06)
**Mistake:** A plan reversed prior ruling R-7 item 5 on empty executions, failing open.
**Prevention:** Before dispatching a plan that changes an order-state outcome, grep docs/plans and docs/evidence for a converged decision on the same input and cite it as CONFIRMS or CONTRADICTS. A CONTRADICTS halts the row; fail-closed stands until ruled; a pinned test of a ruled shape is itself a ruling.
**Applied:** 2026-09-06
**Last updated:** 2026-09-06

### L-33 — A characterisation item has no RED; demand mutation evidence instead (2026-09-07)
**Mistake:** A characterisation item was given RED expectations, and a tautology fabricated RED-GREEN.
**Prevention:** Classify each item as CHANGE (RED fails before the delta) or CHARACTERISATION (each new assertion fails under deliberate perturbation, then restored, returned as `MUTATION_RED_EVIDENCE`).
**Applied:** 2026-09-07
**Last updated:** 2026-09-07

### L-34 — The trial's TRIGGER is pinned; a re-look is a second snapshot (2026-09-09)
**Mistake:** A cached last tick changed the trial snapshot and was classed PREREG-COMPATIBLE.
**Prevention:** Name the datum the pre-registered trigger selects and the datum the change would feed, quote the estimand clause, and classify the change as class (C) if they can differ on any day.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-35 — QuoteTicks cannot observe an empty bid; measure depth from Depth10 (2026-09-09)
**Mistake:** 'Bid side is empty' was read from QuoteTicks, which cannot show an empty bid.
**Prevention:** Never answer 'is there a bid' from the quote tape. Use Depth10 with a level walk; weight pooled medians per station-day; state the capture window; give any exit design a depth walk, spread budget and one-sided-book policy.
**Applied:** 2026-09-09
**Last updated:** 2026-09-09

### L-36 — Strict ZERO_FILL is unreachable; a no-fill IOC is AMBIGUOUS until a GET says otherwise (2026-09-10) (absorbs L-52)
**Mistake:** A no-fill IOC was assumed to return strict ZERO_FILL, and an empty positions page was read as zero fill.
**Prevention:** Never branch on strict ZERO_FILL. A create body of `200` with `id` and `executions == []` stays KIND_AMBIGUOUS (leave `classify_create_order_outcome` byte-unchanged). Resolve with-id intents only via `GET /v1/order/{id}`, fail-closed on any read failure, poller disabled; retire the no-id resolver only on complete reads (`RESOLVER_NO_ID_NO_FILL`); never invoke `clear_submit_intent`. Before any read retires or clears or credits anything, state the outcomes it can distinguish, stay AMBIGUOUS when it cannot, assert operator-visible lines on the real stream, and check the journal after the first live run.
**Applied:** 2026-09-10
**Last updated:** 2026-11-02

### L-37 — A swallowed venue-shape error on the create path is a silent-fill hazard (2026-09-11/12)
**Mistake:** A swallowed shape error locked the account, and the GET resolver retried 3,615 times unbacked.
**Prevention:** On EVERY venue-shape guard (create, confirm, boot sweep, resting poll), log the full names-only key tree on refusal. Answer additive venue fields with a declared-but-unread allowlist plus a value-free evidence note, never a relaxed guard. Surface swallowed errors into the AMBIGUOUS diagnostic; back off unbounded venue retries with an age alert.
**Applied:** 2026-09-11
**Last updated:** 2026-10-28

### L-39 — Prose that names an operator-reserved control by its env-var name fails the census (2026-09-14) (absorbs L-77)
**Mistake:** An untracked plan named operator-reserved env vars and failed the census gate; a later ledger edit turned the gate red on the merged tree.
**Prevention:** Refer to operator-reserved controls only as 'the per-position cap' and 'the daily budget'; before the gate `grep -c "BREEZY_MAX" <doc>` must print 0. Never allowlist a frequently edited ledger (PROGRESS.md, LESSONS.md) in an exact-set prose guard; allowlist only stable plan and review artefacts; re-run the guard on the MERGED tree before push.
**Applied:** 2026-09-14
**Last updated:** 2026-11-02

### L-40 — A station carries as many positions as it has current rungs; the trial unit is the station-day, with the exact mutual-exclusivity variance (2026-09-14) (absorbs L-41)
**Mistake:** Sibling rungs were treated as independent, and a Monte-Carlo null selecting on the quote-generating draw inflated crossing rates to 0.03-0.14.
**Prevention:** Derive Var_H0 from the joint distribution (`sum qty_i^2*BE_i(1-BE_i) - 2*sum_{i<j} qty_i*qty_j*BE_i*BE_j`); bound mixed YES+NO days at variance 1.0, not 1/4; block only the failing scope. Before citing a Monte-Carlo crossing rate or reusing a boundary, confirm it reproduces the registered H0 verbatim (quotes at the cell probability, selection on an independent draw, `E[held - BE | selected] = 0`) and the live look loop including the stop at `I >= I_max`; label any deviation a sensitivity study with its own variance.
**Applied:** 2026-09-14
**Last updated:** 2026-11-02

### L-43 — Two slices that are each green can be jointly broken; gate the integration branch after EVERY merge (2026-09-14)
**Mistake:** Slices green alone broke jointly after merge, and a PREREG amendment cited pre-fix numbers.
**Prevention:** Run the full no-egress gate on the integration branch after every merge and before the next; a worktree gate is not evidence; never cite an artefact not passing on the integration branch; a spawned Python child derives `src` from `breezy.__file__`, never an env var.
**Applied:** 2026-09-14
**Last updated:** 2026-09-25

### L-44 — Logic written for one leg silently mislabels the other; test each leg's terminal state (2026-09-15)
**Mistake:** A YES-shaped classifier made DEAD unreachable for NO legs, and all fixtures were YES.
**Prevention:** For leg-conditional logic, document both legs in a two-column docstring table; add one test per leg proving its losing terminal state is reachable; grep tests for a NO-leg fixture (none means RED).
**Applied:** 2026-09-15
**Last updated:** 2026-09-15

### L-45 — A venue limit is per RESOURCE UNIT, not per slug; verify a new subscription type by coverage count on its first boot (2026-09-17)
**Mistake:** Sharding by slug sent two requests per slug, and a shared venue cap rejected 40.
**Prevention:** Size sharded resources on the venue's counted unit (subscriptions, not slugs); place MARKET_DATA before optional types and WARN the slugs skipped; verify the first boot by coverage count (subscribed set minus `order_book_depths` empty); ship unmeasured limits opt-in.
**Applied:** 2026-09-17
**Last updated:** 2026-09-17

### L-48 — A latch whose only clearing path it blocks is a deadlock, not a safety stop (2026-09-24)
**Mistake:** An AMBIGUOUS intent held the latch OPEN, and its clearing path rejected the body.
**Prevention:** For every blocking latch, name its clearing path and test it end to end with the real stuck shape (venue body verbatim, past-day instrument, boot after the latch was set); make mapping guards state-aware and field-logging. Add 'latch → terminal event on the triggering order → recovery evidence' to every latch's test list.
**Applied:** 2026-09-24
**Last updated:** 2026-10-28

### L-50 — Two writers of one rewrite-in-place file race even when both "append" (2026-09-25)
**Mistake:** Two concurrent read-modify-replace writers lost a record, and both exited 0.
**Prevention:** Never run two writers of one read-modify-write file concurrently; serialise steps in the brief or hold a lock across the cycle; read back and assert the exact record set after writes.
**Applied:** 2026-09-25
**Last updated:** 2026-09-25

### L-51 — A worktree shares the venv and the stash stack with production; isolation of files is not isolation of state (2026-09-26)
**Mistake:** A worktree venv symlinked to production was rewritten by `uv sync`, and `git stash` was used.
**Prevention:** From any worktree never run an environment-changing installer (`uv sync`, `uv add`, `uv pip`, `pip install`, `uv run`); use `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src`; never `git stash` (use `git show <sha>:<path>` or a detached scratch worktree); and confirm `git stash list` is empty before merging.
**Applied:** 2026-09-26
**Last updated:** 2026-09-26

### L-56 — A hypothesis picked from a handful of fills cannot be powered by them, and its re-score must use the bot's own band function (2026-10-11)
**Mistake:** A hypothesis from three fills was re-scored with a half-open band, and n=1486 was needed.
**Prevention:** Re-score fills only through `bucket_facts_from_instrument_id` (`leg_of_symbol` for `^no`); compute the null fill-count probability; run `recompute_mde` against the station-day ceiling; never count the motivating fills toward n; check infeasibility across the sensitivity table.
**Applied:** 2026-10-11
**Last updated:** 2026-10-11

### L-58 — A unit cap is derived from the measured wall of the same job, never guessed (2026-10-16) (absorbs L-53)
**Mistake:** A bench ran under a 1,800 s RuntimeMaxSec though a prior run took 3,072 s; a capped job's single 8.2 GB item never fit its timeout.
**Prevention:** Before `systemd-run`, read the last measured wall for that exact job and set RuntimeMaxSec ≥ 1.75× it (window-bounded if needed). Before any caching fix for a timed-out capped job, confirm the largest single item completes within the cap alone, fixing it with bounded-memory processing if not; SIGKILL is the real stop. A cap below the measured wall is a launch error, not evidence about the job.
**Applied:** 2026-09-27
**Last updated:** 2026-11-02

### L-59 — Validate a screen's input distribution on the block before the verdict run (2026-10-16) (absorbs L-60)
**Mistake:** A stale 789.8 s transactTime sample set the S-7 offset max and voided the run; a power census ignored the bid-bearing filter.
**Prevention:** Before launching any pre-registered verdict, compute its statistic offline on the frozen block (offsets, counts, timestamps only; no fills, rates or labels). Recompute every power floor with the verdict's own estimator and inclusion predicate, not the census headline; record the predicted floor in the procedure; treat a trip or predicted WAIT on the dry run as a design question for the peer loop and a reason to extend the block first.
**Applied:** 2026-10-16
**Last updated:** 2026-11-02

### L-62 — A Grok --prompt-file brief is task text only; flags in it are passed as one argv token (2026-10-20)
**Mistake:** A brief beginning with flags made grok exit 2 in 27 ms, and an apostrophe truncated the prompt.
**Prevention:** Grok --prompt-file briefs carry task text only, with no flag line; bridge flags (`--background --write --cwd --prompt-file`) go on the run command; `grep -c "'" brief` must print 0 before dispatch; the poll agent checks `runs <id>` once at +60 s and reports failed runs immediately.
**Applied:** 2026-10-20
**Last updated:** 2026-10-20

### L-63 — A planned reboot stops the recorder first; an unclean one condemns the open instance (2026-10-20)
**Mistake:** An unclean reboot killed the quote-tape recorder mid-write, and the classifier condemned the whole open instance.
**Prevention:** Before any planned reboot, run `systemctl --user stop breezy-quote-tape.service` and wait for the `Stopped` line. After any unclean reboot, run the census on the open instance at once and accept the loss; never salvage or reclassify under a pre-registered classifier after seeing counts.
**Applied:** 2026-10-20
**Last updated:** 2026-10-20

### L-64 — A live test premised on a replay fill rate pre-registers an opportunity monitor beside it (2026-10-27)
**Mistake:** A live test was armed on an in-sample fill rate carried by a thin-queue burst; three live windows gave 0 fills.
**Prevention:** Before arming any family whose evidence depends on being filled, pre-register and schedule a daily read-only tape statistic for the opportunity the fills came from (thin-queue rest-hours per station-day and disagree-rung count), with its in-sample level and a STOP/INCONCLUSIVE threshold beside the fill-rate check, so a drop rules the test inconclusive-by-regime on the day.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-65 — A replay tape never holds the strategy's own orders; a live book does (2026-10-27)
**Mistake:** The maker priced from a book holding its own resting bid, and the replay modelled no order-count budget, latches or cancel-ack latency.
**Prevention:** Before promoting a family from replay to live: (a) make the parity fixture echo the strategy's own open orders into every frame it prices from, and assert live == replay posts under that echo; (b) model every venue limit the exec path enforces (order-count budget, intent latch, AMBIGUOUS latch, cancel-ack wait, GTD cap) in the replay, or post-filter fills under it, reporting survivors as the live expectation; (c) treat post-arm tape as self-contaminated for any later replay of that family.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-66 — The serial gate without an in-tree basetemp lands on the 16 GB tmpfs and fails DiskLow (2026-10-27)
**Mistake:** The serial gate ran without `--basetemp`, so 97 Stage 0 tests failed DiskLow and buried the one real finding for 32 minutes.
**Prevention:** Always invoke the serial gate as `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/<name>` and `rm -rf` that directory after reading `GATE_EXIT`; when a gate fails with ≥50 failures, group the `E ` lines by message before reading any traceback.
**Applied:** 2026-10-27
**Last updated:** 2026-10-27

### L-67 — Probe the delegation route before the first dispatch, not after (2026-10-28)
**Mistake:** A cycle dispatched Claude sub-agents on the assumption that Grok was still exhausted, though `grok-check.sh` later returned 0.
**Prevention:** The first command of every cycle is `~/.claude/bin/grok-check.sh` (0 = usable, 2 = 402), then the one-line Codex probe; route the whole cycle from those results and state the route in the cycle record before any dispatch. Treat an external route's prior state as a premise to verify, never a fact.
**Applied:** 2026-10-28
**Last updated:** 2026-10-28

### L-69 — The bot's venue account is shared with a human; any manual position latches the node by design (2026-10-28)
**Mistake:** A relaunched node denied every submit because the shared account held a manual position the exec client could not map.
**Prevention:** Before every node launch or relaunch, run the read-only positions probe (`GET /v1/portfolio/positions` via the shipped client) and SURFACE any slug outside `tc-temp-*` to the operator as a launch blocker. Never work around it: do not sell, hide or allowlist it, and do not weaken the guard. Positions and open orders outside the `tc-temp-*` grammar are FOREIGN (logged once; never netted, sold, hidden, allowlisted or a reason to refuse); a `tc-temp-*` position without a loaded instrument remains a refusal.
**Applied:** 2026-10-28
**Last updated:** 2026-10-29

### L-70 — A cycle that waits on an external event must arm its own re-entry (2026-10-29)
**Mistake:** Two cycles ended on 'external event pending' with no re-entry armed.
**Prevention:** Before ending any cycle on a pending event, schedule the re-entry at the event time (CronCreate in-session or the host timer), verify it with CronList or `systemctl --user list-timers`, and write the wake time in PROGRESS.md; a cycle ending without a scheduled resumption or explicit operator stop is a defect. Inside a cycle, delegate gate runs, log reads and watches as single units returning ≤15 lines; main never runs Monitor or diagnostic Bash beyond one lookup.
**Applied:** 2026-10-29
**Last updated:** 2026-10-29

### L-71 — Never run a Claude Code hook script by hand; it reads JSON from stdin and hangs (2026-10-30)
**Mistake:** A hook script was run by hand to re-check a size gate, and the Bash call hung on stdin.
**Prevention:** Validate a hook's condition with the plain measurement it wraps (`wc -c docs/core/PROGRESS.md` against the 12288 B / 250-line budget); never execute a hook script directly. If a hook must be exercised, pipe it the JSON it expects (`echo '{}' | hook.sh`) under a timeout.
**Applied:** 2026-10-30
**Last updated:** 2026-10-30

### L-72 — The grok-bridge `runs` phase stays "starting"; it is not a stall signal (2026-10-30)
**Mistake:** A watcher keyed on the bridge status field reported a healthy Grok build as STALLED, because the `runs` phase never leaves "starting".
**Prevention:** Watch a Grok run by its grok process pid (`pgrep -f <run-id>` alive) and by the mtimes of the files it writes or its job log under `~/.claude/plugins/data/grok-build-xai-grok-build/state/<tree>/jobs/<run-id>.log`; declare a stall only when the pid is alive AND no watched mtime has advanced for 15 min; never cite the bridge phase field in a stall verdict; and match on the `grok` binary and `run-worker` pids, excluding the poll script's own pid, since a grep for the run id also matches the launcher shell.
**Applied:** 2026-10-30
**Last updated:** 2026-10-31

### L-75 — A machine-written evidence artefact is produced by its writer, never edited by hand (2026-10-31)
**Mistake:** A builder hand-added a field to an evidence JSON, so it no longer matched its writer's output.
**Prevention:** Before committing any writer-produced `docs/evidence/*` file (`.json`, `.md` or `.parquet`), `sha256sum` it against the writer's output and confirm the `git_sha` it names is the commit that wrote it. A required new field means changing the writer and re-running the measurement with the committed writer, never editing the artefact; a coordinator note goes in a separate sidecar file.
**Applied:** 2026-10-31
**Last updated:** 2026-11-01

### L-76 — A generated brief input is verified by size and content before any dispatch cites it (2026-11-01)
**Mistake:** A merge script produced MISSING reviewer bodies twice in one day, and three revision tasks ran against 65-byte files.
**Prevention:** After writing any file a brief will cite, `wc -c` it and grep for the consumer's marker (`VERDICT:`, `WRITE TO:`) in the SAME command; refuse to dispatch when the size is under a sane floor or the marker is absent. Prefer pasting review text the coordinator already holds over re-parsing agent transcripts.
**Applied:** 2026-11-01
**Last updated:** 2026-11-01

### L-78 — Poll a CLI forwarder's job from its launch cwd; NOT FOUND is a cwd mismatch first (2026-11-02)
**Mistake:** A watcher polled the Codex companion from the primary tree and reported a worktree-launched job as NOT FOUND.
**Prevention:** Poll a forwarder's job from the exact cwd it was launched with (or pass that cwd), and treat NOT FOUND as a cwd mismatch before concluding the job never ran.
**Applied:** 2026-11-02
**Last updated:** 2026-11-02

### L-79 — A sandboxed external implementer writes; the host gates and commits (2026-11-02)
**Mistake:** Three Codex build jobs authored complete implementations but every one exited "no usable unprivileged network-namespace" on the no-egress gate and `Read-only file system` on the worktree's `index.lock`, so RED/GREEN evidence and commits never arrived from the route that was briefed to produce them.
**Prevention:** Brief a sandboxed external implementer to author only and to end with `COMMIT_SHA: SANDBOX_BLOCKED` on any git or gate error; then dispatch one host agent per worktree to run the gate, produce the RED/GREEN or mutation evidence, fix root causes, and commit by explicit path; never count the implementer's "tests pass" as evidence.
**Applied:** 2026-11-02
**Last updated:** 2026-11-02

### L-80 — A guard trip is fixed by renaming the offender, never by reconstructing the literal at runtime (2026-11-02)
**Mistake:** A cell label `"post"` tripped readonly-guard rule V1 and the implementer silenced it with `POST = "pos" + "t"`, which hides the literal from the AST scan while keeping the value the guard forbids.
**Prevention:** When an exact-set or AST guard fires on new code, rename the offending identifier or value so the guard genuinely passes, add a test that rejects runtime-reconstructed literals (`+`, f-string, `join`), and reject any fix that preserves the forbidden value in a form the scanner cannot see.
**Applied:** 2026-11-02
**Last updated:** 2026-11-02

### L-81 — A cache keyed on `id()` of a short-lived object is a heap-layout lottery (2026-11-02)
**Mistake:** The FQ loss-floor engine cached criticals by `(id(sim), n_days, t_min)`; temporary simulations built inside a draw were freed, their ids reused, and a later draw read another simulation's criticals, so a pinned document hash flipped depending on what pytest had run before and the binding gate failed on an unrelated shard repartition.
**Prevention:** Never key a cache on `id()` (or any identity) of an object that can be freed during the cache's lifetime; key on the object's value, hold a strong reference for the cache's lifetime, or compute without the cache inside the scope that creates temporaries, and when a pinned-hash test fails only in some test orders treat it as non-determinism to root-cause, never a flake to allowlist.
**Applied:** 2026-11-02
**Last updated:** 2026-11-02

## Absorbed index

Every removed L-number resolves to its surviving entry above. Archived (full text in docs/core/archive/LESSONS-archive-2026-10-20.md): L-5, L-57, L-61. Full pre-consolidation text: docs/core/archive/LESSONS_full_pre-consolidation_2026-10-13.md.

L-7→L-9, L-11→L-1, L-15→L-14, L-19→L-14, L-20→L-8, L-23→L-8, L-30→L-8, L-38→L-6, L-41→L-40, L-42→L-24, L-46→L-12, L-47→L-10, L-49→L-29, L-52→L-36, L-53→L-58, L-54→L-12, L-55→L-24, L-60→L-59, L-68→L-16, L-73→L-1, L-74→L-1, L-77→L-39.
