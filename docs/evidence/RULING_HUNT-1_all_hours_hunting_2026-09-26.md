# RULING — HUNT-1 all-hours hunting: BLOCKED-OPEN (gated), not moot (2026-09-26)

**Authority.** This is the strategy-lead ruling that AUD-01 §5/§12 explicitly leaves undecided.

**How it was ruled.** Two agents were briefed blind and separately:
- `trading-bot-architect` (AUTHOR) proposed CLOSE-AS-MOOT.
- `prediction-market-reviewer` (ADVERSARIAL) proposed BLOCKED-OPEN.

The coordinator resolved the contradiction below. No operator-reserved value is involved.

## Question
`daf81a1` found that no testable hour clears zero. Should HUNT-1 be closed as moot, or should a scoped all-hours build be named?

## Evidence (both drafts agree on all of it)
- **`daf81a1` is not a powered negative.**
  - It measured ask-relative edge at θ=0.0695 (the correct post-drift value) over 245 cells and 76 station-days, but covered only **7 of 24 LST hours (09–15)**.
  - None of those hours passes Holm. Hour 11 is nominally significant and negative (p=0.028, Holm 0.196).
  - The CIs are 0.15–0.35 wide.
  - The other 17 hours are **unmeasured** (1–6 clusters each), not zero.
  - The study is YES-only.
- **Why the untested hours are thin.** The refusals at the tested hours include 772 `no_liftable_quote_in_the_hour`: off-peak books are thin by mechanism.
- **Two structural gates refuse almost all decisions regardless of window width.** They are `observation_ambiguous` (the feed reports whole °C; no live sub-degree source exists) and `illegal_cell` (`DECISION_FUNNEL_2026-09-20.md`). The archive table `P_HOLD` for the live `[12,17)` window covers `hour_lst` 12–16 only.
- **Forecast edge on this surface is TERMINAL** (`RULING_forecast_edge_programme_closes_2026-09-20.md`).
- **Building all-hours would cost two governance changes:**
  - a PREREG class-C amendment (new family, n reset, L-34);
  - a change to the permit-TTL safety bound (`CONTINUOUS_HUNTING_GAP_2026-09-20.md` §4/§6).
- **Contradiction resolved.** Closing HUNT-1 as moot was already done on 09-20 and **reversed the same day** (`9ddcb8b`) on the operator's explicit statement: *"there is a definitive requirement that the trading bot's strategy must be continuously hunting, never inside just a specific window."* AUD-01 round-1 review also rejected relabelling it as moot (`AUD-01…md:149-163`). A build-side ruling cannot declare an operator-stated requirement moot. The author's closure reasoning is correct about the *build*, not about the *requirement*.

## Disposition: BLOCKED-OPEN
- **The requirement stands.** HUNT-1 remains an open, operator-mandated requirement.
- **Nothing is built today.** No evidence-backed all-hours build exists. Do **not** widen `_WINDOW_START/END_HOUR_LST`, extend the archive table to all hours, or extend NO-side hunting past AUD-01a's gate.
- **It stays out of active work.** Its severity goes from CRIT to **CRIT/GATED**: tracked, not worked. The next session must not re-open it unless a trigger below has fired.

## Re-open triggers (any one; each is falsifiable)
1. Any hour in 00–08 or 16–23 reaches **≥15 clusters** on the live tape (`daf81a1`'s own power floor). Re-run `hourly_ask_relative_edge.py` for that hour alone. A point estimate that clears fee plus margin makes that hour a candidate for a registered hypothesis.
2. A genuine **live sub-degree observation source** is found, which re-opens the `observation_ambiguous` gate.
3. AUD-18 archive recalibration reaches **CONFIRMED** (not UNDERPOWERED) and changes the `p_hold` estimand materially.
4. A materially different family or estimand is proposed for off-window hours. That proposal enters through AUD-18 registration, never by widening the window.

## Consequences
- In PROGRESS, the HUNT-1 row reads **CRIT/GATED** and cites this ruling and its triggers.
- AUD-01, AUD-05 and AUD-18 are unchanged.
- Never again treat HUNT-1 as moot.
