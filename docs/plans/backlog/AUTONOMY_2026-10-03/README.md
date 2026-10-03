# Autonomy backlog — 2026-10-03

**Objective (operator, 2026-10-03, verbatim):** "The objective is that the trading bot operates and
trades completely autonomously. Store each area in detail in the backlog. Then create peer-reviewed
plans for each area and associate them together. Success can only be claimed for each area when the
execution results in a score of 3, on that scale of 0-3."

Source analysis: the read-only self-learning effectiveness audit of 2026-10-02 (three blind
agents: code feedback-loop trace, MLOps lifecycle review, live operations audit), merged by the
coordinator. Headline: **the bot does not learn from its own outcomes**. Every fitted artefact is
frozen and promoted by a human commit; outcome jobs are report-only; the current sender
`pm_us_crh_fq_v1` has no scorer, so its outcomes are not measured at all.

**Planning only. Nothing in this directory is implemented.** Ruling of record:
`docs/evidence/RULING_operator_full_autonomy_2026-10-03.md`.

## Scale (binding on every area)

| Score | Meaning |
|---|---|
| 0 | Absent. |
| 1 | Exists, but manual, partial, or does not cover the live sending family. |
| 2 | Automated, with a gap: not family-agnostic, not wired to an action, alert not delivered, or not proven live. |
| 3 | **All** of: (a) fully unattended, with no human or agent commit in the loop; (b) family-agnostic, so every registered family, including any future one, is covered by construction and a family cannot send without it; (c) fails closed; (d) each failure mode is detected and alerted with delivery proven; (e) tested RED→GREEN in the gate; (f) **proven live by artefact evidence**, meeting the area's live-proof criterion below. |

**Success rule.** An area is DONE only when an independent reviewer that did not build it scores the
**executed** result 3 against this file, citing artefact paths, log lines and commit SHAs. A merged plan
and a green gate count as score 2 at most. A claim from the agent that built it is not evidence.

**Live-proof window rule (ARCH §5.3).** A day counts toward any N-day live-proof window only if it
has at least one real fill, or a clearly tagged synthetic canary fill that traverses the production
path. Zero-fill days do not count, and the window extends. Every window also needs at least 5 real
fills, and canary fills never count toward that or any statistic. Each DONE claim states its
evidence class: "machinery proven, edge unproven" unless a pre-registered edge verdict passed.

## Binding constraints (every area, every plan)

- Nautilus Trader is immutable; extend only through native mechanisms (L-1 null hypothesis per increment).
- The two operator caps (max daily budget, max per position) are never assigned, derived upward, or
  bypassed by the bot. All autonomy operates **inside** them.
- `allow_short` stays `False`. Never weaken a safety, settlement, contract or NO-SEND firewall test.
- Autonomy selects and retires families and artefacts **inside the already-enabled live envelope**. It
  never flips the master real-money enablement, the permit mechanism or the NO-SEND egress firewall.
  Demotion is always permitted and means stop new entries while exits stay live (the existing family halt also blocks exits and can strand a position, so it is not by itself fail-safe; ARCH C5); promotion only follows a pre-registered
  policy (AUT-5).
- PREREG semantics change only through a ruling under `docs/evidence/`. Automated promotion therefore
  executes a **pre-registered policy ruling**; it never invents statistical semantics at runtime.
- Durable processes run under systemd; memory caps, stall watches and OnFailure delivery apply.
- A plan must reach the goal state (score 3), not merely an increment, and must name its live-proof
  evidence and how long it takes to accrue.

## Current scores (2026-10-02 audit)

| ID | Area | Now | Target |
|---|---|---|---|
| AUT-1 | Data capture | 2 | 3 |
| AUT-2 | Outcome labeling (scoring, P&L, reconciliation) | 1 | 3 |
| AUT-3 | Retraining (refit pipeline) | 0 | 3 |
| AUT-4 | Evaluation (offline challenger + live sequential) | 2 | 3 |
| AUT-5 | Automated promotion and demotion | 1 | 3 |
| AUT-6 | Drift and health monitoring | 2 | 3 |
| AUT-7 | Rollback | 2 | 3 |

## Area detail

### AUT-1 — Data capture (now 2)
**Evidence.**
- What exists: the quote-tape recorder and ingest (catalog `polymarket_us`), NBP ingest, the decision funnel, the durable exec-fill store (`~/.local/share/breezy/state/exec_polymarket_us.sqlite`, 18 fills).
- Gap: the recorder can sit "active (running)" while disconnected and capturing nothing (memory note `recorder-hangs-disconnected`).
- Corrected 10-03 (P1-1): the NBP feed **has** positive log lines, `NBM_NBP_PUBLISHED` (`ingest/nbm_quantile_actor.py:546`) and `FQ_VECTOR_COMPLETE` (`strategy/ladder_ev/forecast_subscriber.py:218`), live since FQ-S6 (`FQ_GO_LIVE_PLAN_2026-10-01.md` F8). Gap: nothing detects their **absence**.
- Corrected 10-03 (P1-2): Breezy's WebSocket idle timeout is configured at 600 s (`adapters/polymarket_us/config.py:293`), not 60 s; dead-peer detection is the separate native heartbeat timeout.
- Gap: there is no single decision-to-order-to-fill-to-settlement join key that covers every family; the exit study reports `no_taken_latch` for the FQ family.
- Gap: the forecast inputs and artefact sha used for each decision are not proven to be captured per decision.

**Score-3 criterion.**
- What must be captured, durably, for every family: every decision (including refusals and their reasons), intent, order, fill, cancel, position mark, settlement, the depth snapshot at decision time, and the forecast or model inputs with artefact sha.
- Every record is schema-versioned and joinable on one decision id.
- A daily completeness audit runs automatically and alerts on any gap.
- A recorder hang or an empty feed is detected and self-healed with no human action.

**Live proof:** 7 consecutive UTC days with 100% join completeness for every live fill, from decision to settlement, plus at least one detected and self-healed recorder or feed stall (an injected one is acceptable if no natural stall occurs).

### AUT-2 — Outcome labeling (now 1)
**Evidence.**
- Gap: `score-live-trials`, the family tallies, `portfolio-roi` and `replay-daily` all SKIP for the current sender, because they only handle `continuous_rung_hold` (the 10-02 logs).
- Gap: admissible n = 0 (`PROGRESS.md`).
- Gap: the position monitor shows FQ "SETTLED n=1 realized_pnl -0.37", which conflicts with the v4 tally's +0.37 on 3 filled takes. It is probably a mislabelled row or a sign error.
- Gap: `portfolio-roi` on 09-30 reported `settled_reconciliation_passes=False`.
- Gap: exit fills are written by `record_exit` (`exit_wiring.py:227`) and never evaluated.
- Gap: `portfolio-roi` exits 1 every day (an expected failure, which makes alert noise).

**Score-3 criterion.**
- Scoring is a family-agnostic scorer contract. A family manifest cannot register or send without a scorer, enforced by a registration-time test.
- Every fill, entry or exit, YES or NO leg, is labelled automatically within 24 h of settlement with: the settled outcome, the realised P&L net of the reconciled fee, the forecast probability at decision, and the counterfactual hold result for exits.
- Labels are reconciled against venue settlement and balance evidence within a stated tolerance.
- Sign and leg conventions are pinned by tests: the venue nets a NO holding as short YES.
- No unit fails as a matter of expected behaviour.

**Live proof:** every live fill over 7 consecutive days is labelled, with reconciliation passing on each day, covering at least one NO-leg fill if one occurs and at least one exit if one occurs. All of it is run by the timers with no hand step.

### AUT-3 — Retraining (now 0)
**Evidence.**
- What exists: `nbp_learning_nightly` (02:05Z) only SCORES the pinned artefact `nbp_validate_candidate_2026-09-30.json` against weather and settlement truth; it fits nothing (corrected by the ARCH pass).
- Gap: no refit consumes the bot's own labelled outcomes; WP-21 ("refit from scored outcomes") is a plan only (`docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md`).
- Gap: `P_HOLD` is frozen on the 2021–2025 corpus.
- Gap: the live loader refuses any `recalibration` other than `none` (`calibration_artefact.py:281-287`).
- Gap: the nightly job's latest run gave `bss_vs_m1=-0.0399` (the candidate scores worse than its baseline).

**Score-3 criterion.**
- Scheduled, unattended refits produce versioned candidate artefacts for each family's model class. Each candidate records its lineage: data window hashes, code sha, parameters and seed.
- Each refit runs on a rolling window of external weather data **plus** the bot's own labelled outcomes and execution data (fill, slippage and refusal), where the model class consumes them.
- Leakage guards are asserted in code (`ref.ts < take.ts`; holdout bounds).
- Refits are reproducible bit for bit from their lineage.
- Each run has a stall watch and a memory cap.
- The loader accepts every recalibration form the pipeline can emit, each covered by parity tests.

**Live proof:** 7 consecutive scheduled refit runs, each lineage-complete and consumed automatically by AUT-4. A run's outcome may be a minted candidate, `NO_CHANGE(below_delta)`, `NOT_FITTABLE` or `MINT_REFUSED_CEILING`, each recorded as a lineage record (reconciles with the frozen ARCH rate limits: at most 1 mint per lineage per day, and α charged per nomination with at most 1 nomination per window; ALPHA decision amendment). At least one minted candidate's training set must include the bot's own labelled outcomes and meet the functional, non-vacuous X22 threshold: at least `MIN_GATE_DECISIONS_CHANGED` probe gate decisions changed relative to the parent, measured on the envelope bounds (coordinator ruling in reviews/AUT-3-r2-merged.md). Coordinator amendment 2026-10-03, per the AUT-3 r1 review R6.

### AUT-4 — Evaluation (now 2)
**Evidence.**
- What exists: the pre-registered splits, the sealed holdout, bootstrap ΔBrier, the LD-OBF/Wilson sequential tests (PREREG v2), shadow parity, and `promotion_criteria.py`.
- Gap: the tallies skip for FQ.
- Gap: the recalibration choice rests on a single validation split.
- Gap: the traded-rung calibration leg is failing and under-confident, and the BSS headline was computed on the wrong family (memory note `bss-headline-is-the-wrong-family`).
- Gap: the replay `replay-daily` failed on 09-30 (MIA timeout) and cannot measure slippage.
- Gap: the verdicts are files that nothing consumes.

**Score-3 criterion.**
- Every candidate from AUT-3 is evaluated automatically against the current champion on pre-registered, cost-aware metrics: out-of-sample Brier/CRPS, traded-rung calibration, and EV net of fees and slippage.
- Every live family is evaluated daily on AUT-2 labels with the pre-registered sequential tests.
- Every result is a machine-readable, schema-versioned verdict that AUT-5 consumes.
- Every verdict states its own power or `n_min` and its time to verdict.

**Live proof:** 7 consecutive days of automatic offline and live verdicts for every live family and every new candidate, each consumed by the AUT-5 policy engine as its input record.

### AUT-5 — Automated promotion and demotion (now 1)
**Evidence.**
- What exists: `promotion_criteria.py` and `promotion_proposal.py` emit a PROPOSAL only, and never arm a family or edit a manifest.
- Gap: arming a family is a manual manifest and env commit.
- Gap: there is no CHAMPION/CHALLENGER registry; WP-20 is a plan only.
- Gap: halting a family is human-only (`set_family_halt_cli`; the A1 halt on `pm_us_crh_v4`).
- Gap: no negative sequential verdict, drawdown or KILL clock halts anything automatically.

**Score-3 criterion.**
- A durable registry of families and artefacts with the state machine SHADOW → CHALLENGER → CHAMPION → RETIRED.
- An automated policy engine executes a **pre-registered promotion policy ruling**:
  - It promotes a challenger to live-send, or swaps an artefact, when that policy's evidence thresholds are met.
  - It demotes or halts automatically on a negative sequential verdict, a drawdown limit, drift (AUT-6) or a failed health check.
  - Every action stays within the operator caps and inside the enabled envelope.
- Every transition is audited, alerted with delivery, and idempotent across restarts.
- The supervisor and node pick up a transition with no code change and no human commit.

**Live proof:** PROMOTE, DEMOTE and RESUME each carried out live end to end through the production engine with no human or agent commit, with evidence in the registry chain, the export and the node log. The AUT-7b drill (ARCH §5.3: a byte-identical child of the champion promoted, demoted by an injected RECOVERABLE fault through the live detector path, resumed, then rolled back) satisfies this. An injected fault counts only if it runs through the live code path.

### AUT-6 — Drift and health monitoring (now 2)
**Evidence.**
- What exists: `check_drift` and `check_freshness` in the nightly job, the fee-drift probe, and the shape-drift refusals.
- Corrected 10-03 (P6-1): the fee probe **is** wired for the FQ family (`app/trade.py:828-844`, lazy slug, live on 10-02). Remaining gap: the timers that key off CRH semantics (`FQ_GO_LIVE_PLAN` F7, F9), which AUT-6 re-verifies.
- Gap: failing units still loaded on 10-02: `portfolio-roi`, `discovery-pull` (timeout), `parity-mem-1d`, `parity-mem-7d` and `replay-backfill-0929`.
- Gap: the `HaltDetector` alerts only.
- Gap: a healthy-looking node can be unable to trade, for example with a lapsed permit (memory note `venue-drift-kills-the-node-silently`).

**Score-3 criterion.**
- Detectors cover every live family for:
  - data freshness (tape, NBP and observation feeds)
  - forecast and feature distribution drift
  - calibration drift on live labels
  - fill-rate and slippage drift
  - venue fee and shape drift
  - permit, process and log liveness
  - unit health
- Every detector maps to an action — node-local entry veto (transient conditions, auto-clearing; ARCH C5), halt, demote (through AUT-5), self-heal or alert — with delivery proven.
- No unit fails as a matter of expected behaviour.

**Live proof:** 7 consecutive days with zero unexplained failed units, plus at least one real or injected drift event per action class that produces its mapped action through the live path.

### AUT-7 — Rollback (now 2)
**Evidence.**
- What exists: artefacts and manifests are pinned by sha, so a rollback is a manifest swap.
- Gap: there is no previous-champion pointer, no automated trigger and no tested drill.

**Score-3 criterion.**
- The registry keeps an immutable champion history.
- An automated rollback to the last good champion fires on the AUT-5 or AUT-6 triggers and takes effect within one supervisor cycle, with no code change.
- A failed rollback fails closed by halting the family.
- Drills run on a schedule in the gate and live.

**Live proof (tracked as AUT-7b, with its own clock of at least 4 trading days):** one live rollback drill through the production path, restoring the prior champion and its byte-identical artefact sha, logged, alerted and reversed, with no human commit (ARCH §5.3). After the 2027-01-25 KILL, the state defined in ARCH §5.3 applies.

## Association (dependency graph)

```
AUT-1 capture ──► AUT-2 labeling ──► AUT-3 retraining ──► AUT-4 evaluation ──► AUT-5 promotion
                        │                                       ▲                ▲      │
                        └───────────────────────────────────────┘                │      ▼
                                       AUT-6 drift/health ───────────────────────┘   AUT-7 rollback
```

Shared contracts, defined once in the umbrella architecture (`AUTONOMY_ARCHITECTURE.md`), which every area plan consumes:
- **C1** decision id and capture schema (AUT-1 → 2, 6)
- **C2** scored-outcome label schema (AUT-2 → 3, 4, 6)
- **C3** artefact lineage manifest (AUT-3 → 4, 5, 7)
- **C4** verdict schema (AUT-4, 6 → 5)
- **C5** registry and state machine plus transition audit (AUT-5 ↔ 7)
- **C6** family scorer, evaluator and drift plug-in contract (a family cannot register without it)

## Items

| ID | Plan | Reviewers | Final | Status |
|---|---|---|---|---|
| ARCH | [AUTONOMY_ARCHITECTURE.md](AUTONOMY_ARCHITECTURE.md) **FROZEN Rev 9.2** sha `1b288d0e…` (+ [errata](reviews/ARCH-ERRATA-rev9_2.md)) | architect 97 · trading-bot-architect 96 · security-reviewer 96 | 96 | FROZEN (12 review rounds) |
| AUT-1 | [r8](AUT-1-data-capture_plan_r8.md) sha `bd7f4d8c…` | trading-bot-architect 95 · silent-failure-hunter 95 | 95 | **REOPENED 2026-10-03**: Nautilus-native pressure test refuted §2 'nothing to reuse' (reviews/AUT-1-native-pressure-test.md); native-first r9 owed |
| AUT-2 | [r7](AUT-2-outcome-labeling_plan_r7.md) sha `d935e0f2…` | prediction-market-reviewer 96 · silent-failure-hunter 95 | 95 | **READY** (7 rounds; binding build items in reviews/AUT-2-r7-final.md) |
| AUT-3 | [r6](AUT-3-retraining_plan_r6.md) sha `688dab87…` | mle-reviewer 96 · prediction-market-reviewer 95 | 95 | **READY** (6 rounds; build-time MEDIUM: guard `Persistent=true` catch-up firings against the launch window and blackout) |
| AUT-4 | [r6](AUT-4-evaluation_plan_r6.md) sha `f0055105…` | prediction-market-reviewer 95 · mle-reviewer 95 | 95 | **READY** (6 rounds) |
| AUT-5 | [r7](AUT-5-promotion-demotion_plan_r7.md) sha `5281cf20…` | trading-bot-architect 96 · security-reviewer 95 | 95 | **READY** (7 rounds; binding build items in reviews/AUT-5-r7-final.md) |
| AUT-6 | [r13](AUT-6-drift-health_plan_r13.md) sha `3ccb8ac2…` | trading-bot-architect 95 · silent-failure-hunter 95 | 95 | **READY** (13 rounds; binding build items in reviews/AUT-6-r13-final.md) |
| AUT-7 | [r5](AUT-7-rollback_plan_r5.md) sha `ef779849…` | security-reviewer 95 · architect 95 | 95 | **READY** (5 rounds; binding build items in reviews/AUT-7-r5-final.md) |
| AUT-7b | live PROMOTE/DEMOTE/RESUME/ROLLBACK drill (ARCH §5.3) | planned inside AUT-7 r5 §3.6.5 | — | PLANNED (READY with AUT-7); execution pending |

**Planning status (2026-10-03):** six area plans are READY; AUT-1 is REOPENED for a native-first r9. That is the *planning* bar: two blind reviewers, the lower score at least 95, and zero CRITICAL or HIGH findings. **No area has been executed, and every area's 0–3 score is unchanged.** An area reaches 3 only after its plan is built and its live proof has run, and an independent scorer assigns the 3.

**Build order:** the binding, priority-ordered queue is the `AUTONOMY QUEUE` table in `docs/core/PROGRESS.md`. `/execute-backlog` reads it and takes the first row that is not DONE or GATED and whose prerequisites are DONE. It follows the dependency graph above. Every WP brief must carry, as binding, the area's `reviews/<area>-final.md` build items and the ARCH errata E-1 to E-10, E-7a and E-8a.

**Evidence class:** machinery proven, edge unproven. `promote_enabled=false` until n_min ≤ n_cap.
