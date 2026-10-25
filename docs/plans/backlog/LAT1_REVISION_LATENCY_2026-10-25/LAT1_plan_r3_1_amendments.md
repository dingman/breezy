# LAT-1 r3.1 coordinator amendments (2026-10-25)

These override r3 where they conflict. Peer review state: architect APPROVE (round 3); prediction-market reviewer APPROVE conditional on amendment 1 (round 3, "once it is made, I approve without another round").

1. **KILL-COST uses the raw executable form.** `K_raw = mean(y_raw(t_dec -> t_dec+60m) - cost_e)` on the traded subset (19Z, r+, dP >= tau_primary, permit per R5). KILL only if the upper 95% bound of K_raw is below 0 (wider of the station-day and climate-day clustered bootstrap, B = 20000). The DiD form `K_DiD` is reported as a diagnostic and never kills on its own. Reason: placebo drift that a trader earns is executable profit, and subtracting it could falsely kill a tradable non-causal edge.
2. **Windows aligned.** Every markout and kill statistic runs from t_dec to t_dec + X (not t_a to t_a + X).
3. **One missing-exit definition.** A take is missing-exit when no bid exists in [t_exit, t_exit + W]. That same definition drives INCONCLUSIVE-EXEC (> 25 percent) in Stage 0 and the Stage 1 qualification.
4. **Heartbeat reporting.** Report the share of missing classifications attributable to QuoteTapeGap records vs. heartbeat failure.
5. **Stage 1 framing.** The prereg states that, at about 59 takes and SE about 0.019, Stage 1 mainly ranks variants and excludes clearly negative ones; it is not evidence of edge.
6. **Scope and sequencing.** Build now: Phase P (backfill, provenance, tau), Stage 0, and the scorer-only Stage 1. The engine parity driver and the backtest strategy are deferred until after the Stage 1 go decision and are built only if Stage 2 will run; parity then runs before Stage 2 starts.
7. **Stage 2 go rule.** Stage 2 runs only if the selected variant's Stage 1 point estimate is at least 0.035 USD/take net. Stage 2 is a research validation; at qty 1 its expected value is about 0.03 USD/day.
8. **Exit retry test.** The scorer tests (and later the parity tests) include a fixture where the exit fills inside the W window, not only at t_exit.
