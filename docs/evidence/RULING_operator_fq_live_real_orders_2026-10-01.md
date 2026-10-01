# OPERATOR RULING — forecast_quantile_ladder to live real orders, ASAP (2026-10-01)

**Source:** the operator, in session 2026-10-01. Their instruction was "Set the bot live to use the new strategy". When asked how to go live, they chose **"Real orders ASAP"**: build the missing pieces and switch to real orders as soon as the safety gates pass, with no extended shadow period. On caps they chose **"Keep current caps"**, meaning the max daily budget and max per position already in `operator.env` apply unchanged.

## What this overrides (explicitly, by operator authority)

- `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md`: the pre-registered power rule (validate n_min 592 > 520 → node 4). The operator accepts live trading **without** a powered confirmatory test and **without** S3a/S3b registration evidence.
- Plan S4-gate's ≥14-day shadow-parity period. It is replaced by the safety gates below.
- The operator was told before deciding that there is **no demonstrated edge**. In-sample, M2 is roughly even with M0 and M1 on resolution, and fees make the expected value negative unless an edge exists.

## What this does NOT override (engineering floors, still binding)

- `allow_short = False`.
- The operator caps are enforced per order by `DailySpendLedger` and never altered by the build.
- The permit gate, the NO-SEND firewall for tests, and every safety, settlement and contract test.
- Fail-closed on any bad artefact.
- No order path may be reachable until the enable switch is set by the documented operator path.
- The live calibration transforms must be identical to the analysis path, proved by test.
- The A1 halt on `pm_us_crh_v4` stays as it is. The new family replaces it as the single active family.

## Build gates before the first real order

1. **Peer-reviewed go-live plan.**
2. **Explicit enable path.** `shadow_only=False` only through a REGISTERED manifest carrying this ruling's reference.
3. **Live calibration parity.** Live support for the selected G2.0 correction (linear LST day-length), with a parity test against the analysis implementation.
4. **Margin fix.** Resolve the hours-to-settlement definition mismatch between strategy and spec.
5. **Replay parity.** Pre-freeze replay parity run (SL-13p2) on real tape with zero divergences.
6. **Gates green.** Full gate green; supervisor restart in the 01:00–16:40Z window.
7. **Live proof.** The first live boot proves the permit line, the family line, the forecast feed publishing, and the strategy subscribing.
