# OPERATOR-CONTROLS-MONTHLY-CAP review status (2026-11-02)
- plan_r1.md — security-reviewer: APPROVE; python-reviewer: APPROVE. Peer review CLOSED at r1.
- Build notes (binding): `order_enablement.py:216` is the refusal text site (not :211); `client.py:6715` is `_read_fill_index`; `except DailyBudgetExhausted` at `client.py:7873` must not catch `MonthlyBudgetExhausted`; `aut2.label` closure must cover `trade.py`; month accumulator re-seeds at boot only via `seed_month_spent`; a cross-day same-month settle adjusts only the month total; drop the "codegraph unavailable" notes.
- Operator input: `BREEZY_MAX_MONTHLY_BUDGET_USD` placeholder added to the gitignored operator.env 11-02 (value pending).
