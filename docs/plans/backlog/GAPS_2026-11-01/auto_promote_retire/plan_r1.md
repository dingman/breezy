# AUTO-PROMOTE-RETIRE — revised delta
Status: r1 DRAFT; prediction-market-reviewer, trading-bot-architect and security-reviewer pending. Planning only; nothing implemented.

## Finding → resolution

Review identifiers below follow the architect’s findings A1–A8 and prediction-market findings P1–P9 in `/tmp/claude-1000/-home-jon-breezy/83eea2b1-e18b-40bb-8838-7106bb5f661f/scratchpad/roi_promote_reviews_r0.md:1-19`.

| Finding | Resolution |
|---|---|
| A1; P2/P4: Wilson stop destroys power | Delete Wilson-LB retirement throughout r0. Statistical retirement uses binding futility or terminal exhaustion; Wilson LB stays descriptive (§5). |
| A2; P6: harness ruling unclear | Explicit live forward-trial scope; reuse existing score, artefact and `boundary_for`; loader incompatibility blocks S0 (§3). |
| A3: settlement-order selection | Contiguous fill-time prefix, including residual fills; every fill final; oldest unsettled fill blocks advancement (§5). |
| A4: boot-only retirement | Fresh per-entry restriction read, explicit expiry and production-wired RUNNING-node test (§3/§6). |
| A5: label sandbox gains registry writes | Separate ExecStartPost command and sandbox row; label command/binds unchanged (§3). |
| A6; P7: conditional dollar mechanism | Dollars require STRATEGY-SEARCH survival and later operator arming; savings bounded by capped spend until next slot (§1). |
| A7: crash between HALT and RETIRE | Durable verdict/demand precede transitions; recover HALTED→RETIRED next pass without rescoring (§4/§6). |
| A8: unnamed non-look receipts | Closed proposed receipt vocabulary, explicitly excluding alpha/look advancement (§4). |
| P1: admissible efficacy hides residual losses | Separate admissible and portfolio counts; positive residual-adjusted P&L and no `cell_dead` required; residual LOSS_STOP path (§5). |
| P3: SEARCH contamination | Pin freeze SHA, freeze climate-day cutoff and SEARCH provenance; exclude discovery/pre-freeze observations from both confirmation counts (§5/§6). |
| P5: early terminal undefined | Freeze D_c cutoff and terminal procedure; realised history with `is_terminal=True`, including t<1 (§5). |
| P8: scheduled latency/catch-up | Preserve chronological exact-prefix catch-up; disclose 14h45m nominal inter-slot delay (§4). |
| P9: citations | Re-read requested sources and cite current lines; execution gaps remain explicit (§9). |

## 1 Objective + ROI mechanism

GOAL STATE: each enrolled prospective trial receives durable RETIRE, PROMOTE-ELIGIBLE or CONTINUE decisions, and retirement prevents subsequent entries through production wiring.
WALK: frozen registration → ordered final-fill prefix → admissible score plus portfolio guards → receipt → restrictive demand/registry transition or operator-ready evidence.
Dollars flow only through the operator’s later arming of a family that survives STRATEGY-SEARCH; retirement savings are bounded by the operator-capped spend otherwise possible until the next slot. Neither eligibility nor automation establishes positive ROI.

## 2 Preconditions/dependencies

- Build after ROI-LEDGER’s decision accessor/schema-6 delivery; use only `read_roi_for_decision`, with its declared freshness/quality gates, for ledger consumption (`docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-01_r2.md:8-14`).
- Retain GAP-4 S0–S2, GAP-3 selection, GAP-5 mechanics, conditional GAP-1/GAP-2 dependencies and all three accepted build notes (`docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/plan_r1.md:28-33`; `docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/review_status.md:3-6`).
- Generalise GAP-4 S3–S7 into repeatable prospective enrolment, retaining separate registration commit, future d0, artefact pins, shadow proof and operator-only arming (`docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/plan_r1.md:50-54`).
- Require sanctioned C5 admission, supported trial units and proven entry/exit handling. Preserve existing trials unchanged; incompatible policies require a separately reviewed prospective registration.
- Require `labels_consumable`; missing/stale markers, identity failure and pending/unresolved/missing labels block consumption (`src/breezy/persistence/autonomy/label_store.py:201-210`).

## 3 Scope and runtime contract

- This is a **live forward-trial decision**, reusing the existing score, `BoundaryArtefact.boundary_for` and pinned artefact; **no backtest harness**, replay runner or new generator.
- Extend `src/breezy/analysis/promotion_criteria.py` with a pure adapter calling existing settlement scoring; keep advisory criteria separate. Existing result structures and fixed-floor criteria remain intact (`src/breezy/analysis/promotion_criteria.py:94-132,486-496`).
- Reuse `src/breezy/settlement/current_rung_hold_v2.py::score` only for its supported YES/per-fill population; unsupported dependence or units remain BLOCKED (`:150-179`).
- GAP-4 note 3 binds: generator output not loadable as FQ `boundary_artefact_path` → **BLOCKED-NEEDS-PLAN**, without writing a replacement generator (`docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/review_status.md:6`).
- Add proposed `src/breezy/analysis/registered_trial_decision_cli.py` as the decision command. Leave `src/breezy/analysis/labeling/label_run.py` unchanged; its studies lock releases in `:599-600`.
- Add one ExecStartPost to `deploy/systemd/breezy-label-outcomes.service`, invoking `breezy-autonomy-bwrap breezy-registered-trial-decisions …/.venv/bin/python3 -I -m breezy.analysis.registered_trial_decision_cli`; no new unit/timer.
- Add its own row in `src/breezy/runtime/autonomy_sandbox/table.py`: no network/credentials; read-only inputs; writes limited to registry/engine-lock/demand, registry exports and existing verdict storage. Keep the label ExecStart and label-row binds unchanged (`deploy/systemd/breezy-label-outcomes.service:31-33`; `src/breezy/runtime/autonomy_sandbox/table.py:315-334`).
- Use existing storage paths, not another ledger/cursor database (`src/breezy/persistence/autonomy/paths.py:125-146,168-174`). S0 must prove the proposed receipt fields fit the governed verdict schema.
- Add proposed `resolve_trial_entry_restriction` in `src/breezy/persistence/autonomy/resolver.py`; inject it through `src/breezy/app/trade.py::_compose_forecast_quantile_ladder` as an additional restrictive veto, preserving existing vetoes (`src/breezy/app/trade.py:836-840`).
- **Per-entry read site:** FQ `try_submit`’s `_submit_veto()` call, before order construction/submission (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:629-643,666-688`). Freshly read registry state, `scan_demands` and the required family pass receipt on every attempt; no cached positive authorization.
- Freeze read-to-entry bound ≤1 second; elapsed/clock ambiguity refuses entry. Pass completion expires at the next scheduled slot: entries remain withheld until that slot’s family pass completes successfully. Missing/unreadable/invalid required evidence refuses entry.
- `scan_demands` already vetoes unreadable/malformed demand data, but treats missing directories as no demand; the enrolled-trial wrapper must additionally require its provisioned directory and current completion receipt (`src/breezy/persistence/autonomy/demand.py:250-289`).
- Withhold the family’s routed permit on boot/restart when restricted; retain per-entry checks for RUNNING nodes. Boot routing currently occurs before composition (`src/breezy/app/trade.py:1300-1314`). Other composition kinds stay BLOCKED until their production entry/cancel paths pass equivalent tests.
- Supersede r0’s Wilson policy and in-process post-label coupling; retain GAP-4’s descriptive Wilson treatment. Defer autonomous arming, sender swaps, RESUME, allowlist widening, sizing and broader AUT-5 capabilities.

## 4 Steps — inputs, outputs, owner, time

| Step | Inputs → action → output | Owner | Estimate |
|---|---|---|---|
| S0 | Sources, generator, loader, C5 gates and runtime seams → compatibility/population/resource review → frozen implementation contract or BLOCKED-NEEDS-PLAN | implementer + reviewers | 1 day |
| S1 | Approved prospective family → artefacts, PREREG/deploy policy, separate registration commit and future d0 → enrolled trial | implementer | 0.5 day/family |
| S2 | Frozen policy → RED-first pure adapter and count/financial guards → evaluator evidence | implementer | 1 day |
| S3 | Final labels, fill inventory, residual sidecar and ROI view → exact prefixes, chronological looks and immutable receipts → decision history | implementer | 1 day |
| S4 | Durable retirement verdict → demand, legal transitions and production restriction → STOPPED only after permit-withhold and RUNNING-entry-refusal tests | implementer | 1 day |
| S5 | Separate ExecStartPost/row → sandbox, closure/pin and measured resource checks → bounded existing-unit execution | implementer + security reviewer | 1 day |
| S6 | Shadow registration and full gate → production-default fixture walk and ready-to-arm evidence → operator handoff | implementer + operator | 1 shadow day |

Process missed admissible looks n_a=10,20,… chronologically on their exact prefixes; stop statistical processing at the first completed terminal verdict.
Slots remain 05:00/14:15 UTC: maximum nominal inter-slot gap is 14h45m, plus run time; settlement and missed slots add latency (`deploy/systemd/breezy-label-outcomes.timer:9-14`).
Proposed non-look receipts: PASS_STARTED, PASS_COMPLETE, NO_NEW_INFORMATION, WAIT_OLDEST_UNSETTLED, INPUT_GATED, BLOCKED_UNSUPPORTED, INTEGRITY_REFUSAL, PORTFOLIO_LOSS_STOP, TERMINAL_NO_INFORMATION, RETIREMENT_PENDING and RETIREMENT_APPLIED. None increments look number or spends alpha.
Use immutable, collision-checked verdict writes; derive progress from receipts, never a mutable cursor (`src/breezy/persistence/autonomy/verdict.py:524-549`).
Persist retirement verdict and restrictive demand before transition appends; publish PASS_COMPLETE only after required effects succeed. Missing completion keeps the current slot restricted.
Under engine lock, append with CAS; reread/retry rather than rewrite history (`src/breezy/persistence/autonomy/registry_store.py:466-517,528-554`). Reconcile pending retirements before attempting new looks.
CHAMPION uses HALT→HALTED→RETIRE→RETIRED; HALTED/SHADOW/CHALLENGER retire directly, preserving DAILY masks and cause vocabulary (`src/breezy/persistence/autonomy/transitions.py:83-92,117-131`; `src/breezy/persistence/autonomy/schemas.py:121-134`).

## 5 Frozen decision rules and count bases

- **Registration:** pin family/lineage, manifest/calibration/boundary hashes, solver identity, policy hash, d0/D_c, n_max, freeze SHA/day, SEARCH exclusions, fill identity/order, fee/payout units, residual classifier, strata and terminal procedure.
- **FQ-R14:** SEARCH/scan/screen observations never count; climate days at or before the cutoff bound to `spec_freeze_sha` never count, even if subsequently relabelled. Require strictly post-freeze, post-registration forward days; SHA is provenance, not a date comparison (`docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_r3.md:243-246`; `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md:441-445`).
- **Prefix P:** contiguous prefix of enrolled forward fills in frozen `(fill_timestamp_ns, durable_fill_identity)` order, with every fill final. Build from the fill inventory before filtering admissibility; a look waits on the oldest unsettled fill, including a residual fill.
- **Admissible n_a:** number of admissible scored fills in P; drives ordinary looks, n_max, S/I/t and boundaries. ZERO_FILL, residual, excluded, SEARCH, shadow/dry/canary rows never increment n_a.
- **Portfolio n_p:** all distinct enrolled forward fills in P, including residuals; reconcile n_p=n_a+n_residual+n_other_excluded. Report unresolved exposure separately; incomplete classification or unreconciled units blocks eligibility.
- **Financial basis:** eligibility and retirement also inspect the complete current portfolio set, never n_a alone. Discovery rows remain outside confirmation; unrelated historical losses remain disclosed in ROI-LEDGER.
- **Residual accounting:** `total_pnl = scored_pnl − residual`, with residual an unsigned loss magnitude; each fill classified once, residual-sidecar exclusions override scored admission. Preserve contract-unit accounting separately from dollar ROI (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:82-98,123-144`).
- **Score:** on n_a only, BE_i=registered entry ask+per-contract fee, 0<BE_i<1; S=Σ(win−BE)/√I, I=ΣBE(1−BE), I_max=n_max/4, t=min(1,I/I_max) (`scripts/analysis/crh_group_sequential_boundaries.py:11-23`). Freeze execution-price reconciliation; never switch price conventions after outcomes.
- **Boundaries:** call pinned `boundary_for(full_realised_t_history)`, α=0.025 each side; never interpolate the reference fixture for live decisions (`src/breezy/persistence/gs_boundary_artefact.py:139-174,183-199`).
- **Statistical retirement:** RETIRE iff S≤b_fut, or terminal exhaustion without full eligibility. **Delete Wilson-LB retirement entirely**; pooled Wilson LB is descriptive (`docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/plan_r1.md:59-64`).
- **Eligibility:** require S≥b_eff on n_a **AND total_pnl>0 on n_p AND no cell_dead**, plus complete financial/safety evidence. Nonpositive P&L blocks eligibility but alone does not create an interim significance stop (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:46,82`).
- **cell_dead basis:** use the frozen admissible station/ask-band stratum count m_a and existing upper-Wilson rule m_a≥60; never substitute portfolio n_p or the deleted pooled-LB rule (`src/breezy/settlement/current_rung_hold_v2.py:385-400`). Here it vetoes eligibility; this delta adds no cell_dead early-stop policy or amendment to existing trials.
- **Residual-driven retirement:** retain the applicable registered §5 LOSS_STOP, checked on portfolio total_pnl every pass even when n_a has not advanced; crossing terminates RETIRE without another statistical look. The v3 threshold is −60 contract-units, not an operator dollar cap; incompatible family units block enrolment (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:82-99`).
- **Priority:** binding existing safety/portfolio LOSS_STOP → RETIRE; otherwise admissible futility → RETIRE; otherwise full eligibility → PROMOTE-ELIGIBLE; otherwise terminal exhaustion → RETIRE; otherwise CONTINUE. Gated inputs withhold entry and eligibility without inventing a statistical verdict.
- **D_c/n_max terminal:** freeze the fill cutoff, withhold new entries, wait for oldest unsettled fills, then use realised t_history with `is_terminal=True`, including t<1. Do not force t=1; if the endpoint coincides with an unconsumed scheduled look, evaluate it once as terminal (`src/breezy/persistence/gs_boundary_artefact.py:183-199`; `docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/review_status.md:5`).
- With no information beyond an already consumed look, issue TERMINAL_NO_INFORMATION and retire for exhaustion; never reopen that look. Eligibility ends the trial; later monitoring requires separate prospective registration.
- **S0 feasibility:** preserve projected power≥0.80 and reachability before registration; run existing `simulate_fixed_pi`/`simulate_drift`, pin inputs/results, and disclose their limitations. Fixed-pi uses the canonical grid; drift uses fixed U(0.20,0.60) asks, θ=0.06 and interpolated boundaries, so neither proves arbitrary-family operating characteristics (`scripts/analysis/crh_group_sequential_boundaries.py:196-236,247-282`; `docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/plan_r1.md:47,61-62`).

## 6 RED-first tests and gate

- CHANGE tests: 9/10/19/20 admissible fills; chronological catch-up; residual fills increment n_p only; oldest unsettled scored/residual fill blocks the next look despite later finals.
- CHANGE tests: SEARCH/scan/screen and pre-/same-freeze-day rows increment neither confirmation count nor look/alpha; post-freeze forward rows count.
- CHANGE tests: efficacy with scored_pnl>0 but total_pnl≤0 refuses eligibility; total_pnl=0 refuses; cell_dead refuses; residual-only updates cross LOSS_STOP with unchanged n_a; no double-counting residuals.
- CHANGE tests: low Wilson LB with S>b_fut continues; heterogeneous BE; boundary equalities; D_c at t<1 matches `boundary_for(history,is_terminal=True)`; coincident terminal look occurs once; no-information timeout never rescores.
- Integration tests: production writers and default composition wiring; RUNNING FQ node refuses its next entry after demand/retirement; restart withholds routed permit; unreadable/missing required demand/receipt, expired slot and read bound refuse; exits remain available.
- Crash tests: verdict→demand, demand→HALT, **HALT→RETIRE**, RETIRE→completion; HALTED restart refuses entry and next pass finishes RETIRE without another look or duplicate transition.
- Test label/decision sandbox isolation, exactly one ExecStartPost pass, released studies lock, no registry write from label command, and no live decisions from measure/canary/shadow runs.
- Preserve prefix hashes; revised consumed labels refuse integrity rather than rescore. Latest-label deduplication already rejects conflicting equal-sequence content (`src/breezy/persistence/autonomy/label_store.py:399-405`).
- Characterisation checks use mutation-fails→restored-GREEN evidence. Run focused tests, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/auto-promote-retire`; inspect EXIT before any later push (`docs/core/LESSONS.md:176-178,354-356`).

## 7 Pins/isolation/risks

- S0 must execute generator→FQ loader compatibility: loader fixes I_max=40 and α=0.025 and checks the schedule grid; no silent loader relaxation (`src/breezy/persistence/gs_boundary_artefact.py:269-282`).
- Measure both commands and whole-unit wall/RSS; fit reviewed timeouts/memory/slot gates or BLOCK. Existing unit budgets are already allocated; do not append unbudgeted execution (`deploy/systemd/breezy-label-outcomes.service:2-10,27-33`).
- Re-pin affected closures through reviewed changes; shared sandbox-table changes require both label and health re-pins (`src/breezy/persistence/autonomy/pins.py:16-22`). Keep stage policy unchanged.
- Nautilus immutable; allow_short=False; preserve safety/settlement/pin/NO-SEND tests, holdout cl.1–cl.4 and L-34; no caps/q, enablement/firewall changes, credentials/order IDs or `iem_cli_fetch.fetch`. Preserve L-75 machine evidence via writer reruns and separate annotations (`docs/core/LESSONS.md:409-411`).
- Family-local α does not establish portfolio-wide false-promotion control; preserve search lineage/multiplicity disclosures. Unsupported correlations, residual units or cancellation semantics remain BLOCKED.

## 8 Operator decisions

Only the operator later selects/arms a sender and supplies sizing, daily budget and per-position cap. PROMOTE-ELIGIBLE is evidence, not a permit or new registry state; existing states are unchanged (`src/breezy/persistence/autonomy/schemas.py:83-88`).
Reviewers approve the prospective policy, slot-based entry withholding and exact scope before registration; no Wilson-cost waiver remains.

## 9 Unverified / execution limits

- Generator→FQ loading, family-specific power/reachability, residual reconciliation and prereg checker execution remain S0 work; no simulations or tests ran here.
- Proposed command, receipts and runtime restriction wiring are requirements, not verified delivery; actual stop/cancel latency and resource fit remain unmeasured.
- Live installation, label freshness and service behavior were not checked; Sequential Thinking/codegraph tools were unavailable, so inspection used direct source reads.
- No files were edited, created or staged. Git status before/after showed the pre-existing modification to `docs/core/PROGRESS.md`.

Codex session ID: 01a19978-b891-7022-8f27-4180c7fbc370
Resume in Codex: codex resume 01a19978-b891-7022-8f27-4180c7fbc370
