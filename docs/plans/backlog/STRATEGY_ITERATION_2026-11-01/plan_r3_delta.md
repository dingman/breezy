# STRATEGY-SEARCH — plan r3 delta
Status: DRAFT; architect and prediction-market-reviewer re-review required. Planning only; operator pause remains binding.
Supersedes r2 wherever they differ, including its output location, running-K threshold, daily dispatch limit and guard-generated templates.
Review IDs below refer to `/tmp/claude-1000/-home-jon-breezy/83eea2b1-e18b-40bb-8838-7106bb5f661f/scratchpad/roi_search_reviews_r2.md:1-17`.

## Finding → resolution

| Finding | Resolution |
|---|---|
| A1 / P5: one cell daily cannot reach N=240 | One collection per daily invocation; sequential batch of up to nine eligible frozen cells under one uninterrupted lock; individual reservations, directories and tested-cell checks (§4–5). |
| A2: overwrites and timer writes inside git tree | Restore r1 D4 derived root; refuse existing run directories; create-exclusive files throughout; coordinator alone copies and commits evidence (§3–4). |
| A3: SHADOW-only handoff lacks enforcement | Exact allowlist: `Kind.MINT`, `from_state=None`, `to_state=State.SHADOW`; exhaustive rejection and protected-write tests (§5–6). |
| A4: lock/resource declarations lack mechanisms | Explicit flock ExecStart, 12G/16G caps, studies slice, descriptor limit and executable contract tests; remove full-gate exclusion claim (§7). |
| A5: guard generates its own input; duplicate K arithmetic | Coordinator writes stubs; guard only validates; guard and scan import one shared accounting function (§3). |
| A6 / P5: running K undercorrects early screens | Freeze `alpha_search=0.05/K_max`, `K_max=S+240`; running K is descriptive/accounting only (§5). |
| A6 / P1: bootstrap resolution inadequate | Freeze numeric `B=25,000`, admission ceiling `K_max≤1,000`; required `ceil(20·K_max)≤20,000`, leaving at least 5,000 additional draws (§5). |
| P1: five all-positive days can produce tiny p | Freeze per-cell day floor from r1 D6, never below 30, and require positive-day fraction <1; otherwise KILL_UNDERPOWERED (§5–6). |
| P2: rolling search can consume confirmation | One immutable programme-wide `T_search_end`; enforce sealed-window exclusion, training chronology and strictly later confirmation (§5–6). |
| P3: undefined D=28 origin | Admission audit records one start event, SHA and UTC timestamp: Step-B merge if it occurred; otherwise X-SEARCH-INTAKE grant merge (§4). |
| P4: upstream/current comparisons omitted | Debit GAP-1 six cells, F13 primary comparison and GAP-6 four cells when exposed; include each current reservation before evaluation (§5–6). |
| P6: unfrozen R≤3 selection; winner’s curse | First three PASSes in serial reservation order receive permanently consumed slots; handoff contains no effect size (§5). |
| A-LOW: unsupported LOW admission; wrong p field | Reject LOW at admission; search uses raw `p_one_sided`, never scan-local `p_bonferroni` (§3, §5). |
| A-LOW: session/tool footer | Remove r2’s Codex footer and tool-availability note. |
| P-LOW: economic honesty, conjunction and fee hurdle | Restore “≈ $0 at qty 1 until a family passes”; require both statistical clauses; distinguish actual-ask excess from band-maximum screening (§1, §5). |

## 1. Objective + ROI mechanism

- GOAL STATE: admitted cells receive reproducible terminal dispositions; eligible PASSes reach acknowledged SHADOW admission through AUTO-PROMOTE-RETIRE.
- WALK: coordinator stub → committed freeze → validated prerequisites/accounting → reserved batch → one collection → sequential single-cell evaluations → immutable verdicts → restricted handoffs.
- ROI mechanism: increase useful discovery throughput before downstream confirmation and deployment. **≈ $0 at qty 1 until a family passes** is the planning assumption, not a measured return forecast; r1 D10 supplies the economic caution (`docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r1_delta.md:39`).
- Report terminal cells/day, collection/evaluation wall time, compute-hours/cell, dependency refusals, remaining budget and acknowledged handoffs.

## 2. Preconditions/dependencies

- Retain r2’s GAP-1/2/3/6, ROI-LEDGER and AUTO-PROMOTE-RETIRE dependencies; SEARCH never substitutes for GAP-4 confirmation (`docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r2_delta.md:14-20`).
- GAP-1 J3/F13 and GAP-6 s0 remain their existing single looks; consume immutable results without rerunning them for queue cells.
- Additional source emitters and executable, fee-aware Kalshi scoring require their named grants and implemented routes. Unsupported HIGH routes remain WAITING until closure; LOW rows are refused outright.
- Existing CLI accepts catalog/truth/out/resamples/seed only; proposed search and forecast modes require implementation (`scripts/analysis/market_calibration_scan.py:860-877`).

## 3. Scope: exact files/flags

- Retain r2’s queue, template and coordinator-authored `docs/prereg/PREREG_STRATEGY_SEARCH_<cell_id>.json` paths (`docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r2_delta.md:25-28`).
- **Drop `--strategy-search-template`.** Coordinator prepares unscored stubs; `prereg_precommit_check.py --strategy-search QUEUE` validates only. Preserve its default FQ schema and committed-blob checks (`scripts/analysis/prereg_precommit_check.py:298-315,323-368,379-398`).
- Add proposed `src/breezy/analysis/strategy_search_accounting.py` containing one pure `reconstruct_search_accounting(...)` function imported by guard and scan; no duplicated seed/debit/budget arithmetic and no evaluator in that module.
- `market_calibration_scan.py --search-queue QUEUE` owns batch selection, bounded collection, single-cell filtering, reservations, verdicts and delivery records; no dispatcher or replacement evaluator.
- Reject unknown fields, duplicate identities, LOW surfaces and unsupported execution conventions at admission. Current directory classification excludes non-HIGH markets (`scripts/analysis/market_calibration_scan.py:191-205`).
- All machine run files remain beneath `~/.local/share/breezy/derived/strategy_iteration/`, restoring r1 D4 (`docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r1_delta.md:19`).
- Explicitly supersede GAP-3’s contrary output-path amendment (`docs/plans/backlog/GAPS_2026-11-01/gap3_confidence_binned_backtest/plan_r1.md:8,44`).
- Implement a search-only exclusive writer restricted to that resolved derived subtree, rejecting symlink escapes. Preserve default `_refuse_live_root` and its tests: today it rejects this root, while `write_outputs` overwrites files (`scripts/analysis/market_calibration_scan.py:840-857`).
- X-SEARCH-INTAKE must explicitly cover this scoped writer, shared accounting helper, collection-date restriction, queue validation/evaluation modes, tests and direct service/timer.

## 4. Steps: owner, inputs, outputs, time

1. **Admission audit — coordinator, ≈0.5 day:** reconcile historical comparisons and immutable evidence; freeze programme ID, seed S, numeric K_max/B, all candidate definitions, ordering, prerequisites, slot rule and T_search_end before outcome inspection.
2. Record `start_event`, merge SHA and exact UTC timestamp. Use the historical Step-B merge if evidenced; if Step B never merged, use the X-SEARCH-INTAKE grant merge. This is the only start ever recorded; missing evidence blocks scoring.
3. Freeze `deadline=start_timestamp+28 days`; activation, downtime, dependency delays and lock contention never restart it.
4. **Implementation/review — implementer then architect/PM reviewers, estimate 2–3 days after dependencies:** RED-first; preserve default scan bytes and existing statistical helpers; benchmark before enabling scheduling.
5. **Freeze — coordinator:** commit completed stubs, stamp the ancestor SHA separately, then validate canonical equality excluding only `frozen_sha`, following the existing guard mechanism (`scripts/analysis/prereg_precommit_check.py:323-368`).
6. **Daily dispatch:** under the service’s single flock hold, validate programme/input/writer hashes and select up to nine earliest eligible frozen rows in queue order; ties use cell_id. Never select by observed statistics.
7. Before outcome-bearing collection, exclusively create each `runs/<run_id>/` and durable `reservation.json`; all reserved cells count immediately. Refuse an existing directory, even empty; crashes burn reservations.
8. Load truth and **collect exactly once** for the invocation’s frozen date/input scope; exclude forbidden dates before collection/joins. Reuse collected observations for sequential cell-specific forecast joins and filters. Current main invokes collect once per process (`scripts/analysis/market_calibration_scan.py:869-877`).
9. Evaluate each reserved cell sequentially through the existing bootstrap; filter to exactly its frozen key first. Assert `tested_cells≤1`, including zero-variance keys; unexpected fan-out halts dispatch and conservatively charges every exposed comparison.
10. Create-exclusive JSON before markdown, followed by verdict/handoff files; never append, overwrite, reuse directories or rescore partial runs. Record reservation, actual tested count, inputs, writer, sample counts, statistics, accounting and disposition.
11. Deliver eligible handoffs without rescoring; acknowledge evidence hash and registry transition ID. Retry delivery only; existing identical acknowledgements are read idempotently.
12. **Coordinator evidence action:** verify writer SHA and byte hashes, then copy/commit artifacts unchanged; notes belong in separate sidecars (`docs/core/LESSONS.md:409-413`). Timer never writes evidence into git.
13. At expiry/exhaustion, close remaining rows with explicit terminal budget/dependency dispositions; no late result newly PASSes.

## 5. Frozen acceptance, accounting and stopping

- **K:** S is the audited historical seed, not an invented total. M1 contributes 35 (`docs/evidence/m1/market_calibration_scan_v2.json:560`); audit P2, Cards A/E, WP-7b, AUD-02 and prior G2/F13 exposures.
- Debit GAP-1’s six cells and F13’s primary comparison, plus the historical G2 look if not already seeded (`docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/plan_r1.md:53-74`).
- Debit GAP-6 s0’s **four** HIGH/LOW × pre/post cells, including reported cells, despite LOW being inadmissible to this scan (`docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/plan_r1.md:87-93`).
- Reserve these comparisons before their outcome exposure, with separate debit records at J3/F13, reader and s0 stages; never defer accounting until handoff. Additional inspected comparisons require additional charges; rereading identical evidence adds none.
- **N=240** covers every post-audit comparison/reservation, including upstream looks and crashes. If all eleven listed upstream comparisons remain, at most **229 scan cells** remain; if already seeded, do not charge twice.
- `K_current=S+all outstanding/completed post-audit debits`, **including the current cell’s reservation**. Missing history or understated K refuses dispatch; exceeding the budget halts the programme.
- **Fixed threshold:** `K_max=S+240`; freeze `alpha_search=0.05/K_max` once. Running K never changes this threshold.
- **Numeric B:** freeze **25,000** draws and seed before scoring; admit only `S≤760`, hence `K_max≤1,000` and `ceil(20·K_max)≤20,000`. Larger audited S requires a reviewed pre-run amendment; never increase B after a failed look. Current default is 10,000 (`src/breezy/settlement/roi_bound.py:93`; imported at `scripts/analysis/market_calibration_scan.py:63`).
- **Reachability:** nine cells/day gives capacity 252 across 28 daily opportunities. Effective scan N is `min(240−upstream_debits, eligible_frozen_cells, 9×remaining_daily_opportunities)`; report this integer at admission and each tick. Capacity is conditional on measured runtime, lock availability and dependencies.
- **Search PASS requires conjunction:** VALID, estimable, powered cell **AND** `p_one_sided≤alpha_search` **AND** `ci95_lo>m`, with frozen `m∈{0.02,0.03,0.05}`. Equality passes the p clause; LB=m fails.
- Use raw p, not `p_bonferroni`: that field multiplies by the local key count, which is one here (`scripts/analysis/market_calibration_scan.py:618,628-638`). SPA remains descriptive.
- Preserve calendar-day clustering across stations; p is `(1+#bootstrap_means≤0)/(B+1)` and LB is the 2.5th percentile (`scripts/analysis/market_calibration_scan.py:543-564,578-600`).
- Freeze `n_days_min=max(30,ceil(D_c))` per cell using an outcome-blind target Δ and r1 D6’s one-sided R=3 rescale: ≈30 days at Δ=15¢, 55 at 10¢, 221 at 5¢ (`docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r1_delta.md:23-31`). Retain n≥30; five days is insufficient.
- Define positive-day fraction over observed calendar days using each day’s aggregate excess; require it **<1**. Too few days/observations or all-positive days ⇒ KILL_UNDERPOWERED; zero variance ⇒ KILL_UNTESTABLE. Preserve existing validity barriers (`scripts/analysis/market_calibration_scan.py:104-109,709-718`).
- Actual-ask hurdle is covered directly: `excess=hit−[ask+fee(ask)]`, with rounded fee evaluated at each actual ask (`scripts/analysis/market_calibration_scan.py:220-228,472-474`). It does **not** prove clearance of the maximum cost anywhere in a band; supersede that r1 wording and retain band maxima as descriptive screens only.
- **Temporal separation:** freeze one UTC T_search_end programme-wide. Guard and scan reject empty windows, any intersection with `[2026-07-01,2026-10-02)`, starts before 10-02, or ends after T_search_end.
- Calibration/emitter training must end strictly before evaluation start and remain before 07-01; provenance gaps refuse evaluation. GAP-4 confirmation days start strictly after T_search_end and its prereg freeze; no SHADOW/confirmation days re-enter SEARCH. Holdout and training chronology follow the ruling (`docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-14`).
- **Slots:** first three PASSes in serial reservation order consume R≤3 permanently, including pending handoffs; no effect-size ranking, replacement after failure or slot recycling.
- Handoff allowlist contains IDs, evidence/prereg/manifest hashes, PASS, slot and **only** `Kind.MINT`, `None→State.SHADOW`; no effect size, p, CI, sizing or enablement fields. Existing MINT permits exactly that transition (`src/breezy/persistence/autonomy/transitions.py:71`).
- Conditional on valid super-uniform p-values, the union bound is `N_effective·0.05/K_max≤0.05`; independence is unnecessary. The small-sample percentile bootstrap does not establish that validity, so this remains SEARCH, never confirmatory FWER proof.

## 6. RED-first tests + gate

- RED: **“same run_id twice refused”**, including empty/partial directories; every output create-exclusive; default live-root refusal preserved; search writer rejects path/symlink escape.
- RED: nine eligible cells invoke collect once, score sequentially under one lock hold, and each has its own pre-read reservation/run directory with tested_cells≤1; fan-out and crash charges persist.
- RED: guard and scan import the same accounting function; current cell included; GAP-1 six + F13 one + s0 four cannot be understated, omitted, recycled or double-counted.
- RED: unknown/unfrozen/changed stubs, LOW admission, missing seeds, N overflow, B below frozen requirement, threshold drift and second start timestamp are refused.
- RED: five-day all-positive cell cannot PASS; ≥30 all-positive days also fail the fraction barrier; per-cell day floor, n floor, zero variance and p/LB boundary cases.
- RED separately: sealed-window intersection, window end after T_search_end, changed programme cutoff, confirmation day at/before cutoff, and calibration/emitter training at/after evaluation start.
- RED exhaustively: PROMOTE, ROOT_ADMIT, ACTIVATE, every other Kind and every target state except SHADOW refused; PASS leaves operator.env, permit and enablement bytes/state unchanged.
- RED: slot order independent of effects; fourth slot refused; handoff rejects effect-size fields; duplicate delivery never rescans; acknowledgement required.
- Run focused/adjacent regressions, then `scripts/ci/run_tests_no_egress.sh --basetemp=/home/jon/breezy/.pytest-tmp/strategy-search`, import/type checks; inspect EXIT before push. These are future checks; none ran during this read-only task.

## 7. Scheduling, pins and isolation

- Proposed ExecStart: `ExecStart=/usr/bin/flock -n $XDG_RUNTIME_DIR/breezy-studies.lock /home/jon/breezy/.venv/bin/python -m scripts.analysis.market_calibration_scan --search-queue /home/jon/breezy/docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/candidate_queue.jsonl`
- Require XDG_RUNTIME_DIR; flock holds across reservation, collection, sequential evaluation and recording. Contention starts no work and consumes no reservation; calendar time still expires. Existing replay uses this lock name and nonblocking acquisition (`deploy/systemd/replay-daily-run.sh:103-120`).
- Set `MemoryHigh=12G`, `MemoryMax=16G`, `Slice=breezy-studies.slice`, `LimitNOFILE=524288`; proposed timer 03:40 UTC, `Persistent=false`, no automatic rescore/restart.
- Add the service explicitly to `test_analysis_units_memory_capped` and assert exact directives, existence and incident commentary; existing tests enforce ceilings/order and incident references (`tests/unit/test_analysis_units_memory_capped.py:29-76,133-165`).
- Add subprocess lock-contention tests proving zero collector calls/reservations; verify installed slice limits, not its name alone (`deploy/systemd/breezy-studies.slice:16-23,30-32`). Remove “never overlap a full gate”; no such exclusion is claimed.
- Preserve Nautilus, allow_short=False, operator caps/q ownership, safety/settlement/contract/pin/NO-SEND barriers; no credentials/order IDs or `iem_cli_fetch.fetch`.

## 8. Operator decisions

- Lift pause and grant the precisely scoped X-SEARCH-INTAKE above; retain separate GAP grants and explicit source/venue extensions. Sizing, literal 70% preference and live enablement remain separate decisions.

## 9. Unverified / required before execution

- Exact audited S/K_max, historical comparison completeness, Step-B/grant merge event and UTC timestamp, and programme T_search_end.
- Implemented GAP dependencies, extra-source/Kalshi scoring routes and AUTO-PROMOTE-RETIRE family/manifest consumer.
- Measured nine-cell runtime/memory capacity, installed timer/slice/lock behaviour and remaining eligible-cell count.
- Proposed RED/GREEN/gate results and statistical calibration; no implementation, tests, deployment or file writes occurred here.

Codex session ID: 01a19978-b925-7d70-aef1-2aad9f05ad1c
Resume in Codex: codex resume 01a19978-b925-7d70-aef1-2aad9f05ad1c
