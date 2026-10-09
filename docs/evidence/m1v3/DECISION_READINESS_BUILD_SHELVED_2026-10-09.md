# DECISION: M1v3-CONFIRM readiness build SHELVED at Stage −1 viability (2026-10-09)

**Decision:** shelve the `pm_us_nolong_d12_v1` readiness build. Its plan is READY r4.2 (d57da900), amended by r4.3 (`docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/M1v3-CONFIRM-readiness_plan_r4_3_delta.md`). The cause is the plan's own Stage −1 viability rule: STOP iff d̂_mix_p90 > 0.30. This is a **measured** population finding: n = 39 ≥ 30, and the V24 representativeness caveat applies.

**Unchanged:**
- The pre-registered M1-v3 read (on or after 2026-12-07) stays as frozen. PREREG.json is untouched.
- RULING_FQ-v2-NO-TRADE stays in force.
- No live surface changed.

**Sunk cost:** about 1 agent-day (the WP-0(c0) count plus the triage), instead of about 30.

## Evidence

### 1. WP-0(c0): pre-10-07 order history

Source: `WP0_c0_pre1007_orders.tsv`, latency and class fields only.

- **Orders:** n = 39 posted. 32 filled on POST; 7 were AMBIGUOUS. p_amb is 0.18 (point estimate) and 0.33 (Wilson upper bound).
- **h_post:** p50 0.169 s, p95 0.304 s.
- **Zero-fill resolution:** 125–144 s, plus one stuck order at 96,824 s.
- **Representativeness:** no order was NO at an ask ≥ 0.90.

### 2. Code: resolver floors

From `src/breezy/adapters/polymarket_us/exec/client.py`:

| Constant | Line | Value |
|---|---|---|
| `_RESOLVER_ZERO_FILL_MIN_AGE_NS` | :1596 | 120 s |
| `_RESOLVER_NO_ID_MIN_AGE_NS` | :1604 | 300 s |
| Resolver poll | :587 | 5 s |

r4.2's 60 s latch bound was a false premise. These floors are byte-pinned safety constants and are never lowered.

### 3. Triage replay (NON-BINDING; pre-window tape 2026-08-30..10-06 only)

Artefacts: `stage_minus1_triage_dmix.py` and `stage_minus1_triage_results.json`.

**Candidates:** 333 candidates on the four main stations (LAX, MDW, MIA, SFO), about 9 per day. 42% of them arrive within 12:00:00–12:00:05Z. The median inter-arrival gap is 1.1 s.

**Drop share d̂ across days.** Model: single global latch, drop-not-queue.

| p_amb | Zero-fill hold | d̂_p50 | d̂_p90 | Verdict |
|---|---|---|---|---|
| 0.10 | 150 s | 0.46 | 0.58 | STOP |
| 0.18 | 150 s | 0.56 | 0.65 | STOP |
| 0.33 | 150 s | 0.69 | 0.74 | STOP |

**Independent re-simulation** by the prediction-market-reviewer (CONFIRMED):
- p_amb = 0 gives d̂_p90 = 0.49.
- p_amb = 0.05 gives d̂_p90 = 0.54.
- Halving the zero-fill hold to 75 s, below the code floor, changes nothing (0.538).
- A 0.05 s post hold gives about 0.41.

### 4. Root cause

The loss is **structural to a serial singleton latch over a burst arrival process.** Even with zero AMBIGUOUS orders and a sub-second hold, about half of the candidates are dropped on a bad day. No parameter within the current design passes the 0.30 limit.

## Consequences and re-open conditions

**Not built:** none of WP-A, WP-1..WP-6 or WP-4, and no branch builds.

**If the 12-07 read returns WINNER:** that is evidence about the screen population. It does **not** re-open this build. A route to trading it would need **a new plan and prereg** for a different execution design: per-rung or parallel intents, or a queueing policy re-screened on its own population. That is a change to the submit-intent safety design and needs the full peer loop.

**ROI ranking:**
- The 12-07 read remains the only scheduled T1 trigger.
- Its trading value is now conditional on a new execution-design plan as well.
- The DECISION_ROI_ROUTE_TO_TRADING_2026-10-09 conclusion stands: no 2026 trading route.

## Lesson

The plan reached READY (95–96 from four peers) with an unverified code premise: the 60 s latch bound. Rules going forward:
- Verify code constants with a file:line reference before peer review.
- Run the cheapest empirical check first.

This is recorded in memory as `readiness-plan-latch-premise-2026-10-09`.
