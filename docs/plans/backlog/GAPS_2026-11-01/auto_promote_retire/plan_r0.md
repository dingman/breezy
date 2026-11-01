# AUTO-PROMOTE-RETIRE — DELTA plan
Status: r0 DRAFT. Reviewers: prediction-market-reviewer, trading-bot-architect, security-reviewer — pending. Read-only planning; nothing implemented.

## 1 Objective + ROI mechanism

GOAL STATE: one scheduled decision pass processes every enrolled family’s frozen forward trial at each successive 10-fill look: RETIRE, PROMOTE-ELIGIBLE, or CONTINUE.
WALK: frozen registration → settled, admissible fills → exact look prefix → centred score and boundaries → durable verdict → existing permit/entry refusal or operator-ready eligibility.
ROI mechanism: stop further spending on failing families and remove manual evidence assembly from winners; the operator retains arming and sizing. Wilson retirement can also stop uncertain winners; that cost is disclosed below.

## 2 Preconditions/dependencies

- Retain GAP-4 r1 S0–S2, GAP-3 selection, GAP-5 mechanics, conditional GAP-1/GAP-2 dependencies, and all three binding notes in `gap4_registered_family/review_status.md`.
- Generalise GAP-4 S3–S7 prospectively: each family gets its own pinned artefacts, PREREG, future d0, registration commit, shadow proof and ready-to-arm record.
- Freeze this decision policy before the family’s first counted fill. An existing PREREG that makes Wilson descriptive only is incompatible: preserve it; enrol a new prospective trial rather than reinterpret its results.
- Require sanctioned C5 enrolment, immutable family/artefact bindings and a proven stop path for each composition kind. Unknown families or unsupported units report BLOCKED; never manufacture registry admission.
- Consume AUT-2 labels through its shared gate: missing/stale markers, identity failure or pending/unresolved/missing labels refuse consumption (`src/breezy/persistence/autonomy/label_store.py:201-210`).
- Preserve holdout ruling cl.1–cl.4, L-34 trigger identity and the 10-21 existing-harness restriction. Any required exception must be named and reviewed before implementation.

## 3 Scope

- Extend `src/breezy/analysis/promotion_criteria.py` with one pure registered-trial evaluator returning existing criterion/result structures; those structures already carry verdicts, thresholds and evidence references (`:94-132`).
- Keep its existing advisory predicates intact. Their station-day bootstrap and fixed sample floor are different estimators, not substitutes for the registered score (`src/breezy/analysis/promotion_criteria.py:486-556`).
- Extend `src/breezy/analysis/labeling/label_run.py` with one post-label decision pass; run after the label studies lock is released, then acquire the existing registry engine lock. The current lock release is in `:599-600`.
- Host it in existing `breezy-label-outcomes.service/timer`: 05:00 and 14:15 UTC, with no additional unit or timer (`deploy/systemd/breezy-label-outcomes.timer:9-14`).
- Do not host it behind the legacy scorer’s success marker: that wrapper exits early for FQ (`deploy/systemd/score-live-trials-run.sh:182-216`).
- Reuse C5 `RegistryStore`, `RegistryReader`, chain/fold and existing verdict/demand writers. No new ledger, cursor database, registry state, kill-switch file or scheduler.
- Extend `src/breezy/persistence/autonomy/resolver.py` with the shared read-only retirement decision; wire its restriction through `src/breezy/app/trade.py` and existing permit/entry seams in `src/breezy/strategy/current_rung_hold/composition.py`.
- Boot routing already supports withholding the sending permit; FQ already checks permit absence and its submit veto (`src/breezy/strategy/current_rung_hold/composition.py:257-291`; `src/breezy/strategy/forecast_quantile_ladder/strategy.py:629-643`). Runtime retirement consumption is proposed work, not shipped functionality.
- Narrowly extend `src/breezy/runtime/autonomy_sandbox/table.py` and the existing label service for registry/demand/export writes; its present bind set lacks registry access (`:315-334`). Update affected closure manifests, source pins and focused contract tests.
- Preserve `scripts/analysis/promotion_proposal.py`’s existing mode: it creates a draft with unpinned artefacts and feeds an absent challenger stream into its criteria (`:192-210,325-342`). That output cannot itself establish eligibility.

Supersession/deferment, limited to families enrolled under this delta:
- Supersede GAP-4 S3–S7’s one-family/manual handoff with repeatable enrolment plus scheduled decisions; retain S3 artefact creation, S4 freeze, S5 separate registration commit, S6 shadow proof and operator-only arming.
- Supersede GAP-4 §5’s descriptive-only Wilson treatment with the explicitly frozen retirement rule below; preserve its centred score, boundary design, feasibility gate and terminal-look review note.
- Supersede AUT-5 r7 §2’s “build engine” prerequisite and WP4’s separate daily/intraday/prelaunch scheduling for this narrow decision loop; reuse the implemented foundation rather than rebuild WP1.
- Supersede AUT-5 §3.9’s station-day Brier/841-day nomination machinery as the eligibility test for this trial; use its own frozen fill-based PREREG. Do not lift those gates for an actual AUT-5 sender swap or refund nomination spending.
- Supersede §3.9 `live.sequential`’s recoverable-HALT endpoint with permanent family retirement here, using legal existing transitions.
- Defer autonomous CHAMPION promotion, allowlist widening/WP9, swaps/ACTIVATE, RESUME, rollback/ROOT_ADMIT, full RegistryWatchActor/ATTEST/dead-man machinery, drawdown producer/WP11 and WP10’s live widening drill.
- AUT-5’s broader safeguards remain binding on those deferred capabilities. This delta does not satisfy its score-3 live-proof claim.

## 4 Steps — inputs, outputs, owner, time

| Step | Inputs → action → outputs | Owner | Estimate |
|---|---|---|---|
| S0 | Verify generator-to-loader compatibility, C5 enrolment and each kind’s existing permit/entry/cancel path; freeze timing, statistical assumptions and exact supersession → reviewed implementation contract; otherwise BLOCKED-NEEDS-PLAN | implementer + named reviewers | 1 day |
| S1 | Generalise GAP-4 S3–S5 → independently pinned family artefacts, machine-readable PREREG/deploy copy, registration commit and future d0; no threshold chosen from forward outcomes | implementer | 0.5 day/family |
| S2 | RED-first pure evaluator in `promotion_criteria.py` → centred score, Wilson guard, decision and evidence fields; reuse existing boundary and interval routines | implementer | 1 day |
| S3 | Verified C5 families + fresh label marker → deterministic admissible fill prefixes and durable look receipts in existing verdict storage; derive progress from receipts, never a separate cursor | implementer | 1 day |
| S4 | RETIRE verdict → legal C5 transitions/demand and existing permit/entry refusal; PROMOTE-ELIGIBLE → immutable operator-ready evidence only | implementer | 1 day |
| S5 | Attach one pass after normal label runs; update narrowly reviewed binds/pins and measure the combined job → bounded existing-unit execution and journal output | implementer | 1 day |
| S6 | Generalised GAP-4 S6–S7 shadow proof, full gate and production-default fixture walk → ready-to-activate report; operator subsequently arms/sizes families | implementer + operator | 1 shadow day |

On each invocation, process missed looks chronologically at n=10,20,… using precisely those prefixes; stop processing that trial at its first terminal decision. Never replace several missed looks with one latest-total look.
“After 10 fills” means ten additional final, admissible scored fills. Scheduling is twice daily: maximum nominal inter-slot delay is 14h45m after labels become consumable, plus run time; settlement delays and missed/held slots add latency.
Persist look receipts and a pass-completion receipt in existing verdict storage; non-look receipts must never spend alpha or advance the look count. Existing verdict writes are immutable and collision-checked (`src/breezy/persistence/autonomy/verdict.py:524-549`).
Freeze prefix ordering and identity; deduplicate label revisions before selection. The existing reader keeps the highest label sequence and rejects conflicting equal-sequence content (`src/breezy/persistence/autonomy/label_store.py:399-450`).
A revision changing an already-consumed prefix is an integrity refusal, never permission to recompute that look. Isolate malformed families, continue independent restrictions, and return an overall failure visibly.

## 5 Acceptance / PASS-KILL frozen

- PREREG pins family/manifest/calibration/boundary hashes, d0, terminal date D_c, n_max, fill identity/order, fee convention, exclusions, dependence assumptions, solver identity and this policy’s hash.
- Ordinary looks occur only every 10 admitted fills. ZERO_FILL, shadow/dry/canary, unresolved or excluded rows never increment n; report censoring separately. Use the shared admissibility selector (`src/breezy/persistence/autonomy/label_store.py:409-418`).
- Define BE_i = registered entry price + registered per-contract fee; require reconciled fee/settlement identity and 0<BE_i<1. Freeze whether “entry price” is decision ask or execution price; never switch between them after observing outcomes.
- Compute S_k = Σ(win_i−BE_i)/√I_k, I_k=ΣBE_i(1−BE_i), I_max=n_max/4 and t_k=min(1,I_k/I_max), as specified by the existing generator (`scripts/analysis/crh_group_sequential_boundaries.py:11-23`).
- Obtain `(b_eff,b_fut)` from the pinned artefact’s `boundary_for(full_t_history)`, α=0.025 one-sided on each side; never interpolate the reference table for live decisions (`src/breezy/persistence/gs_boundary_artefact.py:139-174,183-199`).
- Wilson guard: pooled win-count Wilson 95% LB, z=1.959963984540054, compared with mean(BE_i) over the identical prefix. Reuse interval arithmetic; do not reuse `cell_dead`, which tests the UPPER bound with n≥60 (`src/breezy/settlement/current_rung_hold_v2.py:370-400`).
- Priority: **RETIRE** if S_k≤b_fut OR Wilson LB<mean(BE_i), including at the first look; otherwise **PROMOTE-ELIGIBLE** if S_k≥b_eff; otherwise **CONTINUE**.
- At registered n_max/D_c, use a declared terminal look spending remaining alpha even when t<1; the artefact supports this via `is_terminal=True` (`src/breezy/persistence/gs_boundary_artefact.py:183-199`). With no new information, retire for timeout without reopening an earlier look.
- Terminal exhaustion without eligibility is RETIRE. First crossing ends the trial; post-promotion surveillance requires a separate prospective monitoring registration, never a reset of this test.
- CHAMPION retirement is HALT→RETIRED; HALTED/SHADOW/CHALLENGER can retire directly. Preserve the transition table and DAILY mask (`src/breezy/persistence/autonomy/transitions.py:83-92,117-131`); cite the verdict on both rows, using existing `verdict_fail` on HALT (`src/breezy/persistence/autonomy/schemas.py:121-134`).
- Under engine lock, append through `RegistryStore.append` with CAS; retry by rereading state, not rewriting history. The store already provides transaction, replay and CAS checks (`src/breezy/persistence/autonomy/registry_store.py:466-517,528-554`).
- Commit failure publishes an existing restrictive demand and retries on subsequent passes; the existing engine-demand writer is reusable (`src/breezy/persistence/autonomy/demand.py:374-383`). Missing required pass evidence/demand unreadability must withhold sending through the same permit/entry path.
- Enforce runtime refusal before the next new entry and withhold the permit on every restart. Preserve necessary exits/settlement; resting-order kinds additionally require confirmed existing cancel-path handling before reporting STOPPED.
- Do not rely on calling the manual halt CLI from a running node: it explicitly refuses when the node holds the intent lock (`src/breezy/strategy/current_rung_hold/set_family_halt_cli.py:532-538`).
- PROMOTE-ELIGIBLE is a verdict/report label, never a new C5 state or widening transition; existing states contain no eligibility state (`src/breezy/persistence/autonomy/schemas.py:83-88`). Keep the canonical stage unchanged (`stage_policy.py:23-30`).
- Eligibility report includes hashes, exact prefix/counts, S/I/t, both boundaries, Wilson LB, mean BE, exclusions, feasibility and all outstanding safety blockers. It grants no permit, family selection or size.

## 6 Tests RED-first + gate

- RED→GREEN: 9/10/19/20-fill triggers; catch-up prefixes; lower/upper/equality/continue cases; Wilson-only and simultaneous crossings; heterogeneous prices; terminal t<1; zero-information timeout; unsupported units.
- RED→GREEN: cross-family isolation, duplicate/revised labels, frozen-prefix mutation, missing/stale/gated markers, hash mismatch and crash/replay at verdict, HALT, RETIRE and pass-completion boundaries.
- Integration: real registry/verdict/label writers; production-default wiring; active-node entry refusal, restart permit withholding, exits preserved and existing resting-order cancellation where applicable.
- Negative controls: bypassing the retirement reader or changing a boundary must fail the corresponding tests; restore and rerun GREEN. No assertion/pin/NO-SEND guard weakened.
- Verify the normal label-unit path invokes exactly one decision pass after releasing the studies lock, regardless of proof-hook configuration; skipped/canary/measure modes never produce live decisions.
- Measure combined wall/RSS; preserve existing slot/memory gates and per-command timeout accounting (`deploy/systemd/breezy-label-outcomes.service:27-33`). Do not guess larger limits.
- Focused then full: `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/auto-promote-retire`; read EXIT before push. Run import, closure, sandbox, permit and serialization contracts.

## 7 Pins/isolation/risks

- Nautilus immutable; `allow_short=False`; no cap/q assignment or proposal; no enablement/firewall changes; no credentials/order IDs in repo; never call `iem_cli_fetch.fetch`.
- Keep the job outside permit issuance/order execution; only the existing composition path consumes its restrictive registry evidence. Preserve all existing guards and stage identity.
- Review bind/closure changes and re-pin affected producers; shared closure changes require both label and health re-pins (`src/breezy/persistence/autonomy/pins.py:19-22`).
- Wilson LB below break-even means insufficient positive evidence, not proven negative edge; it may retire profitable families early. Its repeated operational stop is not an α=0.025 harm test.
- α=0.025 is family-local, not a portfolio-wide false-promotion guarantee. Preserve selection disclosure, lineage history and no-recycling rules.
- Correlated sibling fills do not justify independent-Bernoulli variance. S0 must validate the registered population; incompatible families remain BLOCKED rather than silently changing the estimand.
- Machine-written evidence remains immutable; annotations go in separate sidecars (L-75).

## 8 Operator decisions

Operator alone arms/selects a sender and sets size, daily budget and per-position cap. The job may only restrict sending and mark eligibility.
Review must accept the explicit Wilson early-retirement cost and scheduled latency before prospective registration. No existing trial is silently amended.

## 9 Citations not verified

- Generator output→FQ loader execution and `prereg_precommit_check.py` flags remain S0 verification items; no compatibility run was performed.
- Live timer installation, fresh-label availability, combined resource budget and end-to-end stop/cancel latency were not inspected at runtime.
- Statistical operating characteristics with the added Wilson stop, and compatibility of every prospective family’s dependence/fee model, remain unmeasured.
- Proposed retirement-reader wiring and tests do not exist as verified delivery; no tests were run during this read-only planning task.
- Sequential Thinking/codegraph MCP tools were unavailable; source inspection was direct. Git status remained clean; no files were edited, created or staged.

Codex session ID: 01a19961-2ba1-7a32-bbc1-708bb36b4417
Resume in Codex: codex resume 01a19961-2ba1-7a32-bbc1-708bb36b4417
