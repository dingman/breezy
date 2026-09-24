# Audit backlog — 2026-09-21

Source of truth for the gaps: `docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md` (G-01..G-17).
**Planning only — nothing here is implemented, and no live trading behaviour was changed.**

## Counts

- Audit gaps: 17 · backlog items: 20 (G-11 split into AUD-06a/06b; AUD-18 added at the operator's
  direction; AUD-19 created by a ruling) · every gap mapped, none dropped.
- Final score 100/100 from both required reviewers on the same revision hash: 20 of 20.
- **READY: 19 · NOT READY: 1** (AUD-06b, on unavailable evidence — not on a plan defect).
- Review records: 242, in `reviews/<ID>-r<round>-<reviewer>.md`. Rulings: 5, all peer-ENDORSED.

## Gate

Each plan was scored on fidelity 20 / correctness 20 / specificity 15 / acceptance 20 / autonomy 15 /
portfolio 10 by two independent specialist reviewer agents that ran blind to each other. The final
score is the LOWEST reviewer score on the final revision, never an average. Each final record cites
the sha256 of the revision it scored; each plan's closing "Coordinator final status" block carries
that hash (the content above the marker line, less the one separator newline) and is the
authoritative status — it supersedes reviser-written wording in §13. After any edit, both reviewers
re-scored the new hash. Where a reviewer withheld points without naming a defect, a neutral
reconciliation request required either a named defect with an exact required change or restoration
of the points. Baseline is the planner's self-score before any review.

**Readiness rule.** A dependency on another PLANNED item is execution order, not a blocker. A plan is
NOT READY only on unavailable evidence, unavailable access, or a decision that is the operator's.
The operator's budget ceiling is established and is never a blocker; no plan states or proposes a
value for an operator-reserved cap. Live-trading enablement of any family is operator-only and is
outside every plan here.

Routing: Grok was balance-exhausted (402) and plan authoring, review and rulings are Claude-native
coordination surface, so planners, revisers, reviewers and ruling authors were Claude sub-agents.

## Items

| ID | Title | Gap (existing item) | Priority | Baseline | Final | Status | Rounds | Reviewers | Plan |
|---|---|---|---|---|---|---|---|---|---|
| AUD-01 | no side calibration safety gate and station stall diagnosis | G-01 (HUNT-1) | P0 gate / P2 diagnosis | 93 | 100 | READY | r3 | mle-reviewer + prediction-market-reviewer | [AUD-01](AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md) |
| AUD-02 | edge discovery programme status and fold in | G-02 | P1 · 02b P0 | 86 | 100 | READY | r8 | prediction-market-reviewer + silent-failure-hunter | [AUD-02](AUD-02-edge-discovery-programme-status-and-fold-in.md) |
| AUD-03 | daily decision funnel digest | G-17 | P1 | 96 | 100 | READY | r3 | mle-reviewer + prediction-market-reviewer | [AUD-03](AUD-03-daily-decision-funnel-digest.md) |
| AUD-04 | portfolio roi measurement | G-03 | P0 | 78 | 100 | READY | r6 | mle-reviewer + prediction-market-reviewer | [AUD-04](AUD-04-portfolio-roi-measurement.md) |
| AUD-05 | live family tally unit | G-04 (R-4, SP-1 I5) | P1 | 79 | 100 | READY | r8 | mle-reviewer + prediction-market-reviewer | [AUD-05](AUD-05-live-family-tally-unit.md) |
| AUD-06a | r11 boundary revalidation | G-11 (MP-B, R-11) | P2 | 76 | 100 | READY | r5 | mle-reviewer + prediction-market-reviewer | [AUD-06a](AUD-06a-r11-boundary-revalidation.md) |
| AUD-06b | bounded allocation sizing | G-11 (MP-B) | P3 | 74 | 100 | NOT READY | r7 | mle-reviewer + prediction-market-reviewer | [AUD-06b](AUD-06b-bounded-allocation-sizing.md) |
| AUD-07 | exit seam arming verification path | G-12 (EXIT-1) | P2 | 80 | 100 | READY | r6 | mle-reviewer + prediction-market-reviewer | [AUD-07](AUD-07-exit-seam-arming-verification-path.md) |
| AUD-08 | unattended station candidate register | G-05 | P1 (08a) / P3 (register) | 81 | 100 | READY | r5 | architect + trading-bot-architect | [AUD-08](AUD-08-unattended-station-candidate-register.md) |
| AUD-09 | scheduled per station replay | G-06 (SP-4) | P1 | 83 | 100 | READY | r8 | architect + trading-bot-architect | [AUD-09](AUD-09-scheduled-per-station-replay.md) |
| AUD-10 | evidence gated promotion proposal | G-07 (REG-1) | P1 (10a) / P2 (10b) | 84 | 100 | READY | r10 | architect + trading-bot-architect | [AUD-10](AUD-10-evidence-gated-promotion-proposal.md) |
| AUD-11 | point in time backtest guard | G-08 + G-15e | P1 | 87 | 100 | READY | r5 | mle-reviewer + prediction-market-reviewer | [AUD-11](AUD-11-point-in-time-backtest-guard.md) |
| AUD-12 | cost model slippage and fee drift | G-09 | P1 (b) / P2 (a) | 90 | 100 | READY | r4 | mle-reviewer + prediction-market-reviewer | [AUD-12](AUD-12-cost-model-slippage-and-fee-drift.md) |
| AUD-13 | native venue reconciliation from durable records | G-10 (SP-3, R-1, R-2) | P2 (13d P1) | 86 | 100 | READY | r8 | silent-failure-hunter + trading-bot-architect | [AUD-13](AUD-13-native-venue-reconciliation-from-durable-records.md) |
| AUD-14 | hands off operation restart motive and selfcheck escalation | G-13 | P3 (14a) / P1 (14b) | 90 | 100 | READY | r5 | silent-failure-hunter + trading-bot-architect | [AUD-14](AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md) |
| AUD-15 | failing study units fix or retire and alert | G-14 | P1 (15a) / P2 (15b-c) | 90 | 100 | READY | r8 | silent-failure-hunter + trading-bot-architect | [AUD-15](AUD-15-failing-study-units-fix-or-retire-and-alert.md) |
| AUD-16 | evidence hygiene live counts family id and funnel scope | G-15a-d | P2 | 87 | 100 | READY | r2 | silent-failure-hunter + trading-bot-architect | [AUD-16](AUD-16-evidence-hygiene-live-counts-family-id-and-funnel-scope.md) |
| AUD-17 | operator caps proven through the v4 live composition | G-16 | P1 | 92 | 100 | READY | r5 | silent-failure-hunter + trading-bot-architect | [AUD-17](AUD-17-operator-caps-proven-through-the-v4-live-composition.md) |
| AUD-18 | strategy design backtest iterate programme | G-02 (operator-added 2026-09-21) | P1 | 83 | 100 | READY | r10 | mle-reviewer + prediction-market-reviewer | [AUD-18](AUD-18-strategy-design-backtest-iterate-programme.md) |
| AUD-19 | family manifest flag on replay driver | G-06/G-07 (created by the citability ruling) | P1 | 85 | 100 | READY | r5 | silent-failure-hunter + trading-bot-architect | [AUD-19](AUD-19-family-manifest-flag-on-replay-driver.md) |

## Rulings (strategy-lead calls, delegated by the operator to the coordinator + specialist peers)

Each ruling had one author peer and one independent adversarial reviewer, iterated to ENDORSE.
Artefacts are in `docs/evidence/`; review trails in `docs/evidence/reviews/`.

| Ruling | Decides | Consumed by |
|---|---|---|
| `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` | `pm_us_crh_v4` may not SEND orders; node, capture and KILL clock keep running. UNENFORCED until AUD-02b's set-halt CLI lands. | AUD-02, AUD-07 |
| `RULING_venue_reconciliation_R1_R2_2026-09-21.md` | R-1 = O4: fee θ resolved as of fill time, refusal inside the 2026-09-17 00:00–17:00Z ambiguous window; R-2 = R2-B conditional. | AUD-13, AUD-12 |
| `RULING_live_family_tally_scope_2026-09-21.md` | No prefix re-issue; scorer-time guard; `pm_us_crh_cont` retired; NO rows unpartitioned; AUD-05 implements SP-1 I5 (single KILL-clock owner). | AUD-05, AUD-10 |
| `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` | Replay ids keyed on `family_id`; MECHANISM_ONLY never citable; R5-7/R5-8 adapted, PROVISIONAL; AUD-19 created. | AUD-09, AUD-10, AUD-19 |
| `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` (+ addendum) | Retire offer-gate and mb-daily units, re-home the `--since` ASOS refresh in the same commit; R-12 and per-position intent are build-side; exit PREREG draft authorable; positive control is a bot step. | AUD-15, AUD-06b, AUD-07 |

## The one NOT READY item

- **AUD-06b (bounded allocation sizing).** BLOCKER-B, unavailable evidence: sizing above one contract
  needs a CONFIRMED edge from AUD-18 and a newly registered family to carry it. No ruling can
  manufacture that. The plan itself scores 100/100; AUD-06a landing first is sequencing only.

## Stated limits on READY items (not blockers)

- **AUD-02:** the A1 ruling is unenforced until AUD-02b (P0, set-halt CLI) is built and the halt set.
- **AUD-07:** this item arms nothing. The later arming decision needs a family that trades (corpus
  growth), AUD-06a, the halt cleared for the positive control, and operator-only enablement. PREREG
  v4 §5b is flagged `PROVENANCE_POSTDATES_READOUT`, not attested.
- **AUD-10:** until AUD-05's KILL clock and AUD-19's driver flag land, the only output is a
  machine-checked `NO_PROPOSAL`; adapted criteria stay PROVISIONAL pending a lifting ruling.
- **AUD-18:** the pinned power check gives a minimum detectable edge of about 7–10 probability points
  at PM.us sample sizes (primary-test power only), so the expected first disposition is
  `UNDERPOWERED_NOT_REGISTERED` or an evidenced programme KILL, not a confirmed edge.

## Dependencies and execution order

Edges (A → B means B needs A): AUD-02b → enforcement of A1 · AUD-05 → AUD-10 (`C-KILL`) ·
AUD-19a → AUD-19b → AUD-19c · AUD-09 runner → AUD-19c · AUD-19 → AUD-10 (`C-PAIRED`) ·
AUD-09 → AUD-10 (shared wrapper contract) · AUD-08 → AUD-09 (site registry constraint) ·
AUD-09 + AUD-11 + AUD-12 → AUD-18 (replay runner, point-in-time guard, slippage) · AUD-18 CONFIRMED → AUD-06b ·
AUD-06a → AUD-06b · AUD-06a → AUD-07 · AUD-04 → AUD-07 (AUD-04 owns `alert_ladder.py`). No cycle.

1. **P0, first:** AUD-02b (set-halt CLI, enforces A1), AUD-01 safety gate, AUD-04.
2. **Independent, now:** AUD-03, AUD-17, AUD-11, AUD-12b, AUD-14b, AUD-08a, AUD-15 (retire + re-home
   in one commit), AUD-13, AUD-16, AUD-10a (REG-1).
3. **Evidence spine:** AUD-05 (tally + KILL clock) · AUD-09 runner → AUD-19a → 19b → 19c · then AUD-10b.
4. **Strategy:** AUD-06a, AUD-12a, then AUD-18 (own unit, 01:20Z; one heavy study at a time).
5. **Last:** AUD-07 measurement fixes and PREREG draft; AUD-06b only after an AUD-18 CONFIRMED edge.

## Reconciliation

- **Coverage:** G-01→AUD-01 · G-02→AUD-02 + AUD-18 · G-03→AUD-04 · G-04→AUD-05 · G-05→AUD-08 ·
  G-06→AUD-09 + AUD-19 · G-07→AUD-10 · G-08+G-15e→AUD-11 · G-09→AUD-12 · G-10→AUD-13 ·
  G-11→AUD-06a/06b · G-12→AUD-07 · G-13→AUD-14 · G-14→AUD-15 · G-15a–d→AUD-16 · G-16→AUD-17 ·
  G-17→AUD-03.
- **Duplicates avoided:** existing PROGRESS items were extended by reference, not re-opened —
  HUNT-1 (AUD-01), R-4 / SP-1 I5 (AUD-05), MP-B/R-11 (AUD-06a/b), EXIT-1 (AUD-07), SP-4 (AUD-09),
  REG-1 (AUD-10), SP-3/R-1/R-2 (AUD-13). G-15e was folded into AUD-11.
- **Conflicts resolved:** one KILL-clock owner (AUD-05 implements SP-1 I5; AUD-10 consumes). The
  replay-id family scoping is owned by AUD-19a, not AUD-09. The set-halt CLI is AUD-02b, not AUD-01.
  The re-alert ladder exists once (AUD-04 owns, AUD-07 consumes). `max_equity_fraction` is excluded
  from AUD-06a and disposed in AUD-06b. AUD-19 supersedes AUD-09's step-8 `DRIVER_DEFAULTS` pin.
- **Known stale state not fixed here (owned by AUD-16):** `docs/core/PROGRESS.md` live counts
  (:32, :82) and the WP-R1 section (fix landed `e83fc5c`).
