# STRATEGY-SEARCH — standing intake; delta r2 over STRATEGY_ITERATION
Status: r2 DRAFT; required reviewers: **architect** and **prediction-market-reviewer**; reviews pending. Planning only.
Applies over r0+r1; this delta wins on conflicts. Retain GAP-3 r1’s CSV contract and immutable run-directory correction. The operator pause remains binding.

## 1 Objective + ROI mechanism

- GOAL STATE: every admitted `(source, surface, band)` cell reaches a frozen, reproducible search PASS/KILL or a named dependency refusal; every PASS is handed to AUTO-PROMOTE-RETIRE for SHADOW admission.
- ROI mechanism: increase edge-discovery throughput per compute-hour and shorten admission-to-verdict time. All recorded edge verdicts are negative; automation must expose useful new information or stop expenditure, rather than repeatedly tune losing cells.
- WALK: queue → template-generated PREREG → commit/stamp/verify → prerequisite evidence → one existing-harness evaluation → immutable debit/verdict → PASS handoff → registry SHADOW.
- Measure terminal cells/day, compute-hours/cell, waiting reasons and acknowledged SHADOW handoffs. Search throughput is a precondition for profitable deployment, not evidence of realised ROI.

## 2 Preconditions/dependencies

- GAP-1 r1+r2: consume its single J3 look and OOF-reader result; never rerun it per queued cell. Only eligible source/horizon results proceed under GAP-1’s frozen routing.
- GAP-2 r1+r2: forward probability emission requires its named exception. Its current planned source scope is `nbp_fq_v1`; adding a GAP-1 source needs an explicit frozen-artifact emitter extension, not an assumed capability.
- GAP-3 r1 must land before `--forecast-p` use. Today the scan CLI has no such flag: `scripts/analysis/market_calibration_scan.py:860-866`.
- GAP-6 r1+r2+r3: reuse its one `s0` history look and subsequent census; its B-8 ruling and D-2 exception remain prerequisites. `s0` CONTINUE and census PASS establish neither a net edge nor a search PASS.
- AUTO-PROMOTE-RETIRE owns family admission and SHADOW registration; GAP-4 owns subsequent forward confirmation. GAP-5 remains a downstream mechanics dependency.
- Preserve AUD-18’s power-first, one-look discipline and closed-class dispositions; do not migrate its alpha budget into this search.
- AUT-S r2’s AS-R14 still forbids v5 archive minting; reuse its intake discipline, without building its generator, SPA module or additional harness (`AUT-S-winner-search_plan_r2.md:654-656`).
- Startup blockers observed at HEAD `6dd322b6`: `docs/prereg/`, `gap1_oof_murphy.py`, `p2_forward_p_emit.py` and `kalshi_depth_census.py` are absent. Dependencies are planned capabilities.

## 3 Scope: exact files/flags; exclusions

- Queue: `docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/candidate_queue.jsonl`; append ordered intent rows, never overwrite previous candidate definitions.
- Template: `docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/prereg_cell_template.json`; generated stubs: `docs/prereg/PREREG_STRATEGY_SEARCH_<cell_id>.json`.
- Each row specifies `cell_id, source_id, surface, window, side, ask_bin, edge_bin, calibration_sha256, m, input_refs, prerequisite_refs, evaluation_window, run_id, prereg_path`.
- `surface` identifies venue, HIGH/LOW and execution convention; `band` includes both ask and forecast-edge bins. Changed source, window, band, calibration or margin is another charged candidate.
- **Proposed flag on existing guard:** `prereg_precommit_check.py --strategy-search QUEUE`; validate the search schema, frozen blobs, prerequisites and ledger arithmetic.
- **Proposed generation mode on that same script:** `--strategy-search-template TEMPLATE --queue QUEUE`; emit create-exclusive, unscored stubs. Generation never freezes or commits them.
- The guard currently accepts one FQ-design path and rejects unknown keys; search-schema support is new work, preserving the default FQ contract (`scripts/analysis/prereg_precommit_check.py:298-315,379-398`).
- **Proposed flag on existing scan:** `market_calibration_scan.py --search-queue QUEUE`; process at most one eligible frozen cell, using GAP-3’s `--forecast-p`, and exit.
- This flag adds selection, bookkeeping and verdict serialization only. It filters the frozen date/window/side/band before the existing bootstrap; it must not evaluate a full grid and discard unwanted results afterward.
- **Proposed downstream flag**, owned by AUTO-PROMOTE-RETIRE: `promotion_proposal.py --search-pass HANDOFF`; consume the evidence without rescoring. That flag does not exist today (`scripts/analysis/promotion_proposal.py:231-249`).
- Scheduling: proposed `deploy/systemd/breezy-strategy-search.{service,timer}` directly invokes the existing scan with its queue flag; no shell dispatcher, runner module or new evaluator.
- Exact exception **X-SEARCH-INTAKE**, §8, gates these additional modes and scheduling files. A flag is not evidence that new orchestration is already authorised.
- Excluded: statistical rewrites, cross-run SPA, new forecast fits, native harness changes, sizing, trading enablement and execution changes.

## 4 Steps: inputs → outputs; owner; time

1. **Admission audit — coordinator, 0.5 day:** reconcile the historical seed ledger and closed classes; pin programme ID, Step-B merge timestamp and original deadline. Missing seed evidence blocks scored work.
2. **Dependency closure — owning GAP teams, their existing estimates:** obtain reviewed GAP-1/2/3/6 implementations and grants; record immutable evidence references. Do not build replacement readers or evaluators here.
3. **RED → implementation → review — implementer plus architect/PM reviewer, 2–3 days after dependencies:** add only §3’s modes, queue/template and tests; benchmark one fixture before scheduling.
4. **Template generation — guard generation mode, minutes/admission batch:** substitute each queue row into its own stub; refuse duplicate identity, unknown fields, missing pins and unsupported source/surface combinations.
5. **Freeze — coordinator, before evaluation:** commit completed stubs; stamp their commit SHA in a follow-up commit; verify before dispatch. Canonical comparison excludes only `frozen_sha` and requires an ancestor commit (`scripts/analysis/prereg_precommit_check.py:323-368`).
6. **Frozen contents:** template hash, cell definition, m ∈ {0.02,0.03,0.05}, complete input hashes, model provenance, data roles, minimum sample, seed/B, single-look run ID, PASS/KILL rule, ledger seed/head and cumulative-count formula.
7. **Prerequisite routing — coordinator/queue flag, minutes:** reference GAP-1 OOF evidence for forecast cells and GAP-6 `s0` evidence for Kalshi-tail cells. Re-reading an existing result is not another evaluation or debit.
8. **Eligibility:** unsupported cells remain WAITING with an explicit dependency. GAP-6 KILL closes its tail route; CONTINUE cannot bypass the missing executable, fee-aware harness path.
9. **Dispatch — timer, one cell/tick:** select the earliest eligible frozen row; verify committed writer, input bytes and PREREG; reserve its attempt exclusively before opening outcome-bearing inputs.
10. **Evaluate — existing scan, measured runtime:** call its existing collection/scoring/bootstrap path for that single cell. Keep fee/excess and bootstrap unchanged (`scripts/analysis/market_calibration_scan.py:472-474,578-600`).
11. **Record — scan queue mode, same invocation:** write `docs/evidence/strategy_iteration/runs/<run_id>/market_calibration_scan.{json,md}`, plus create-exclusive attempt/verdict records; JSON precedes markdown.
12. **Immutable evidence:** include argv, writer SHA, PREREG/input hashes, selected key, actual tested-cell count, K before/after, N remaining, deadline, sample/day counts, statistics and disposition. Coordinator commentary goes in a separate sidecar.
13. **Handoff — scan then AUTO-PROMOTE-RETIRE, same/next tick:** PASS emits immutable `handoff.json`; downstream acknowledges its hash with registry transition ID. Retry delivery only; never rerun the statistical look.
14. **Operate — daily timer at proposed 03:40 UTC:** `Persistent=false`; one invocation handles one cell, pending delivery, expiry or NO_WORK. Verify the installed schedule and runtime limits before activation.
15. **Close — scan queue mode, deadline/exhaustion:** write programme disposition, stop dispatch and retain every attempt. Reopening requires genuinely new data/venue plus a ruling; it inherits historical K and never silently restarts this episode.

## 5 Acceptance / PASS-KILL frozen

- **Search PASS:** VALID, estimable selected cell with `p_one_sided × K_cum ≤ 0.05` **AND** `ci95_lo > m`; otherwise statistical KILL. Retain per-run SPA descriptively, without gating.
- These fields already exist; the lower bound is the bootstrap’s 2.5th percentile, not a Wilson bound (`scripts/analysis/market_calibration_scan.py:477-507,591-598`).
- Zero variance, insufficient sample or invalid inputs cannot PASS; record reasoned `KILL_UNTESTABLE`, `KILL_UNDERPOWERED` or `REFUSED_INVALID`, without claiming absence of an edge.
- Preserve minimum n=30/day-count=5 and all validity barriers (`scripts/analysis/market_calibration_scan.py:104-105,709-718`). Waiting decisions use outcome-blind readiness only.
- **N:** 240 new cell-units maximum. Reserve one per selected cell; every started attempt burns its reservation, including crashes and untestable outcomes. Actual tested cells must be ≤1; unexpected fan-out halts dispatch and every exposed cell remains charged.
- **D:** 28 calendar days from the original Step-B merge, never from timer activation; lock contention, downtime and waiting consume calendar time. Refuse starts at expiry; no late result can newly PASS.
- **K:** audited historical seeds plus all subsequent tested cells, including discarded/zero-variance cells; unresolved post-outcome crashes retain conservative charges. Never remove failed runs or recycle debits.
- Seed M1=35 is verified (`docs/evidence/m1/market_calibration_scan_v2.json:560`); reconcile P2, Cards A/E, WP-7b, AUD-02 and GAP-1/F13 comparisons without double-counting prior recorded looks.
- The guard reconstructs totals from immutable records, validates historical runs against their own ledger prefix, and refuses missing records or understated prospective K. Freeze the counting rule; record actual K at decision.
- Choose existing `--resamples` before freeze so its p-value resolution can reach `0.05/K_cum`; never increase B after viewing a failed cell (`scripts/analysis/market_calibration_scan.py:598,865`).
- A PASS creates a SHADOW handoff, never nomination evidence. MINT’s existing transition is `None → SHADOW`; registry append owns transactional validation (`src/breezy/persistence/autonomy/transitions.py:71`; `registry_store.py:466-508`).
- SHADOW admission requires AUTO-PROMOTE-RETIRE’s valid family/manifest route; unavailable routes remain `PASS_HANDOFF_PENDING`, visibly blocking delivery acceptance. Preserve R≤3 forward confirmations.
- Running-count screening thresholds do not establish sequential programme-wide confirmatory FWER. Keep the requested search criterion; preserve separately frozen forward confirmation before promotion.

## 6 Tests RED-first + gate

- RED: duplicate admission, incomplete/unfrozen/refrozen stub, changed input/writer, unknown schema, understated K, missing seed history, N overflow, original-deadline expiry and attempted counter reset.
- RED: exactly one cell reaches bootstrap; excluded observations leave numerator and denominator together; boundary-band/date selection; default scan bytes unchanged.
- RED: equality passes the p threshold; LB=m fails; invalid/zero-variance/underpowered cells never PASS; no GAP-1 or `s0` result is relabelled a strategy PASS.
- RED: concurrent ticks, crash after reservation/JSON, partial output, duplicate handoff and delivery retry preserve debits and never rescore; registry acknowledgement is required.
- RED: timer invokes only the existing script; shared lock prevents overlap; resource caps and network isolation work; no live-path write occurs.
- Gate after integration: `scripts/ci/run_tests_no_egress.sh --basetemp=/home/jon/breezy/.pytest-tmp/strategy-search`, then project import/type checks; read EXIT before push. No tests were executed during this read-only planning task.

## 7 Pins/isolation/risks

- Historical nightly-study memory records **10–24 GB** peaks; never overlap heavy work or a full gate ([memory](/home/jon/.claude/projects/-home-jon-breezy/memory/nightly-studies-run-at-10-24gb.md:8), [concurrency rule](/home/jon/.claude/projects/-home-jon-breezy/memory/background-sleeps-die-under-memory-pressure.md:10)).
- Use the shared `breezy-studies.lock` convention (`deploy/systemd/replay-daily-run.sh:103-119`) and `breezy-studies.slice`; its declared aggregate limits are 12G/16G (`deploy/systemd/breezy-studies.slice:30-32`). Benchmark the scan; do not inherit r0’s unmeasured 4G assumption.
- Holdout [2026-07-01,2026-10-02) stays sealed/descriptive as ruled; selection days never become confirmation days (`docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-14`).
- Calendar-day clustering includes all stations together, correcting r1’s station-day wording (`scripts/analysis/market_calibration_scan.py:543-564`). Disclose small-day bootstrap coverage and opportunity frequency.
- Nautilus immutable; `allow_short=False`; safety/settlement/contract/pin/NO-SEND tests unchanged; L-12 and L-75 bind. Never assign/propose caps or q, touch enablement/firewall, expose credentials/order IDs, or call `iem_cli_fetch.fetch`.

## 8 Operator decisions

- Lift the build pause and grant **X-SEARCH-INTAKE exactly for §3’s queue/schema/template modes, one-cell filter/bookkeeping/verdict mode and direct systemd service/timer**; no new evaluator, harness or runner.
- Retain separate GAP-1 D1, GAP-2 and GAP-6 D-2 grants. Additional forecast sources or a Kalshi scoring route require their own precisely scoped extension ruling; absent one, those cells wait.
- Literal 70% preference, sizing and live enablement remain separate operator decisions; this delta changes none.

## 9 Citations not verified

- Historical seed counts beyond M1; complete prior-look inventory and actual Step-B merge/deadline require admission audit.
- GAP implementations, extra-source emitters and Kalshi executable/fee-aware scoring are not present or proven; dependency plans are not execution evidence.
- AUTO-PROMOTE-RETIRE’s consumer flag, family mapping and deployed SHADOW admission are unimplemented/unverified handoff dependencies.
- Current installed timers, memory envelope and lock participation require deployment measurement; cited 10–24 GB figures are historical memory, not current telemetry.
- Sequential Thinking and Codegraph MCP were unavailable; code was checked directly. No files were edited, created or staged.

Codex session ID: 01a19961-2be3-70d1-beee-8a6c17b541f1
Resume in Codex: codex resume 01a19961-2be3-70d1-beee-8a6c17b541f1
