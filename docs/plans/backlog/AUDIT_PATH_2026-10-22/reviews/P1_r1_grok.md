# P1 r1 review — Grok (microstructure / backtest fidelity)

I'll review the plan against the code and the replay data, starting with the plan text and the fill-path implementation it depends on.The design worktree has no codegraph index, so I’ll check the fill simulator and the saved replay outputs directly.**VERDICT = REQUEST-CHANGES**

The 17-vs-20 gap is real and is not a bug. `arm_stats` counts only `stress_pass and win is not None` (`maker_design_score.py:191`); `positions.csv` has 20 `filled` rows and 17 `stress_pass`, and the three base-only rows (MIA 09-27 `gte91f`, MDW 10-06 `gte76lt77f`, LAX 10-11 `gte78f`) are all `win=True` at 0.89. Episodes match: 20 `filled_ns_base`, 17 `filled_ns_stress`. `PositionFold` keeps one row per rung (`maker_stage0_runio.py:219-246`). Sharp has `abstain=False` (`maker_design_config.py:83`). Control is 8 fills, `sum_x` 1.68, `positive_control.differences == []`, but at `code_sha` 206d89ae, not eac99bd6. That commit does not contain `Arm("sharp")`; the sharp run was a dirty tree. Current HEAD is 0d6b4c59.

The latency wrapper is not a correct conservative model. `_on_print` (`maker_stage0_fill_pass.py:222-233`) decrements `r`/`g` for every buyer print with `ts > t0`. Ignoring `ts <= t0+L` means those prints do not consume the queue. `r` stays the t0 snapshot (`:297-310`); depth never refreshes it (`:214-220`). That overstates the queue if the book trades during L (too few fills) and understates it if size joins (too many). Doubling the queue is already how the 17 were counted; it does not price joins during L. Only 2 of 17 stress fills complete before 1s (0.054s, 0.498s); median delay is 1026s. Four base fills are under 10s.

1. Pin the wrapper with sizes: a print inside L must leave `r` unchanged, and a later print fills only from its own size — the plan’s “fills at 2s” test does not say that.
2. Drop G2. At bids 0.81–0.89 both θ values round to a 1¢ fee (`market_calibration_scan.py:228`); the four cells are 1.96 / 1.96 / 1.79 / 1.79, so `mean_x > 0` cannot fail while every fill still wins.
3. G4 must not be terminal. It is 17 fills on 12 days (`n_eff` 13.5, label already UNDERPOWERED); 4 fills have no same-station unfilled rung, and unfilled other rungs bias Δ toward “adverse.”
4. Cut `control_l1`/`control_l5`, the reconcile script, and the sign-flip harness. The 17-vs-20 check is done.
5. Do not hold P4 on this screen. G0–G2 do not test whether the edge survives; a PASS only means fills did not vanish. Optional single arm: sharp at L=1s, stop only if stress fills are under 10 or a settlement loser appears.

Optional: if you want a markout, report the mean YES-mid change in cents next to the ~11.5¢ mean X. No p-value, same station only.

Confidence: 84.
