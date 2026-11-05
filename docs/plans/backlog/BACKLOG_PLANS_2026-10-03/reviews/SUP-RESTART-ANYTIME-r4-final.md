# SUP-RESTART-ANYTIME r4: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| trading-bot-architect | 96 | 0 |
| silent-failure-hunter | 96 | 0 |

Plan: `SUP-RESTART-ANYTIME_plan_r4.md`. **READY.**

## Binding build items (carry them into the implementer brief with the plan)

1. **T12b.** Assert that B1 `NO_NODE` pages immediately on fresh state (`launch_done=False`, so `midday_budget_live` is False). Check that the `deferred_candidate` branch at `core:1622-1631` does not return DEFERRED first. Do not assume this; assert it.
2. **Comment on `decide_ready_adoption_alert`.** It states the assumptions behind the CRITICAL bound. T7d keeps the arithmetic visible: terminal flapping gives at most 36 (470/13).
3. **SM3 re-measurement (§6/§10).** It is MERGE-BLOCKING and is run at PR time. The evidence today covers 2 FQ trading days.
4. **README line.** Hand relaunches mirror `spawn()`. A hand launch with a full TTL widens the R1 anchor.

## Accepted residuals

- **R2.** Non-FQ nodes page instead of marking.
- **R9.** Webhook delivery is best effort. The CRITICAL re-fires every 60 polls.
- **R11 / C0.** A restart in [17:00, 17:05) goes unpaged for at most 5 min.
