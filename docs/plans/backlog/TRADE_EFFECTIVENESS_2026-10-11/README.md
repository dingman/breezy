# TRADE EFFECTIVENESS backlog (2026-10-11)

Source audit: `docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md` (34 live fills, 2 wins, −4.63 net; FQ v1 0/25; NO-side 2/3).

| ID | Item | Overlaps (must be planned as a DELTA, never a parallel build) |
|---|---|---|
| TE-1 | Live P&L self-report for every family incl. FQ; end portfolio_roi NO_INPUT | FQ-LOSS-RESPONSE r3 §W1 (`ForecastQuantileLadderScorer`, `GATED_UNLABELLED_FQ`), F4 labels (promote waits AUT-6), AUT-2, `score_live_trials` |
| TE-2 | Root-cause FQ v1 0/25 before any re-arm | F0 FQ-STEP0 (M1 scan LAX/MIA 10-04), `docs/evidence/FQ_LOSS_TRIAGE_2026-10-04.md`, F13 US sources, FQ-v2 NO-TRADE ruling T1–T3 |
| TE-3 | NO-side longshot hypothesis (2/3 wins at 9–12 c) as a prereg forward test | NO-1, M1-v3 (frozen, read-once ≥ 12-07 — never peek), PREREG rules, rest_v5 shadow |

## Planning protocol
Plan rN → parallel peer review (domain + stack + architecture + Codex adversarial) → merge → rN+1, until every reviewer returns READY with no open BLOCKER/HIGH. Reviews in `reviews/<ID>-r<N>-<reviewer>.md`; convergence record `reviews/<ID>-final.md`.

## Binding on every plan
Nautilus Trader immutable, native-first (L-1 null hypothesis per increment). `allow_short=False`. Never weaken safety/settlement/contract/NO-SEND tests. Never touch live enablement, arming, halts, or the two operator caps. PREREG semantics change only via a ruling under `docs/evidence/`. M1-v3 outcome data is never read before 12-07. The goal STATE is the acceptance test (a plan must reach it). Verify code constants and premises against the code before review. Build execution routes Grok → Codex → Claude tdd-guide; the coordinator runs `scripts/ci/run_tests_no_egress.sh`.
