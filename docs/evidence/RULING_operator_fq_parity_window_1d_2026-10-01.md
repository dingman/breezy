# OPERATOR RULING — SL-13p2 parity window cut to one day (2026-10-01)

**Source:** the operator, in session at 2026-10-01 ~13:17Z: "reduce the 27-day run to 1 day, I want the bot to be armed with the forecasting data as soon as possible."

**Overrides:** the go-live runbook §5 step 2 requirement of "at least 14 distinct days" (plan `FQ_GO_LIVE_PLAN_2026-10-01.md`), for gate 5 of `RULING_operator_fq_live_real_orders_2026-10-01.md`. That ruling file is unchanged; its sha is pinned by the S5 enable gate.

**Still binding on the one day:** zero mismatches, zero numeric mismatches, the vacuity guard, the pinned calibration sha, and the production slippage floor on both legs.

**Result** (`SL13P2_parity_pm_us_crh_fq_v1_2026-10-01.json`). The day is 2026-09-25, the latest pre-freeze day.

| Quantity | Value |
|---|---|
| Decisions matched | 720597 of 720597 |
| `n_mismatches` | 0 |
| `n_numeric_mismatches` | 0 |
| YES Take, live / batch | 7 / 7 |
| `vacuity_guard_failures` | [] |
| `no_side_unexercisable_in_window` | true |

Because NO is unexercisable on the tape for the manifest stations, the NO path rests on the S4b synthetic NO parity test, which is green in the full gate. The live data client also refuses NO-leg subscriptions (`adapters/polymarket_us/data.py`), so the family trades YES only live.

**Coverage given up:** multi-day effects, such as cycle/era boundaries and D+1 day-boundary handling across many days. Before the one-day cut, 1 day (09-01), 3 days (09-02..04) and 09-14 had also replayed with 0 mismatches on the same fixes. A 27-day run is a follow-up, not a gate.
