# STRAT-DESIGN r2 / prereg_r2 — merged review (2026-10-31 ~06:40Z)

prediction-market-reviewer (criteria) + trading-bot-architect (engine verdict, exception, data sources), blind. Verdict: **REVISE
prereg → r2.1, then FREEZE**. Run 2 (Card D G0) is BLOCKED (H1). Run 1 (Card E) proceeds after J1–J7.

## J1 Card E rule (replaces k=3/half Bonferroni; power at a true 5% rate was 0.33/side, 0.013 at 2%)
Two tiers, α split 0.025 + 0.025 (FWER ≤ 0.05):
- T1 pooled exact one-sided binomial over all frozen station-side-days (N ≈ 48 × ~85), p0 = 1%, α = 0.025 (≈ k ≥ 54 at N ≈ 4080;
  evaluator computes the exact threshold). Power at 5%: 0.13 if 1 side affected, 0.47 if 3, 0.90 if 6, ≈1 if ≥12.
- T2 per-side Holm over 48 sides, α = 0.025, exact binomial on pooled days, p0 = 1%: k ≥ 6 at n = 90/71, k ≥ 5 at n = 65/63.
  Per-side power at 5% ≈ 0.25–0.30 — state openly that a single-station basis cannot be certified at 90 days.
- Sign: a flagged side needs ≥ 80% of its mismatches in one direction; direction not fixed ex ante. Chronological half-split =
  stability check only, never a gate.
- PASS = T1 OR T2 (with the sign rule). KILL = T1 not rejected AND exact one-sided 95% UCB on the pooled rate ≤ 2.0%. Else
  INCONCLUSIVE (incl. short sides; short sides stay in T1). Every station-side outcome is one of PASS/KILL/INCONCLUSIVE (H3).
- Mismatch = int(expiration_value) − CLI_final_int ≠ 0 at degree level; null/non-numeric expiration_value, void/cancelled markets and
  CLI amendments EXCLUDED (delete "amendments and voids are mismatches"); bucket-level check (`result` vs CLI-implied bucket) reported,
  not gated. Freeze the CLI pull timestamp (10-30 may not be final on 10-31); join on the climate date in `event_ticker`.
- Window per side = days with both labels, frozen from the availability pull (row counts only were seen: Kalshi 91/91 for 18 cities,
  MSP 90, SAN 71, SDF 63, EWR 65, TTN 65; IEM 91 except PHX 89, SAN 90); drop the "n < 118 → INCONCLUSIVE" clause.
- LOW sides need a tmin parser (`CliLabel` has tmax_f only, `settlement_alignment_study.py:111`) + tests, or drop LOW from m = 48 (H2).
- Prize paragraph moves out of the prereg or is labelled non-binding.

## J2 Run 2 (Card D G0) BLOCKED
`us_source_archive/metar-routine` covers 5 stations to 2026-06-30 and `read_routine_metar` refuses past `HOLDOUT_START`. Name a
post-July source (`src/breezy/ingest/iem_observations.py` or the observation sidecar) with its own coverage, or mark D G0 moot. If
kept: grid denominator (named stations × 2026-09-21..10-30), per-station timezone table (10:00 LST Pacific = 18:00Z, not 17:00Z),
frame-days and METAR-days reported separately, per-station floor ≥ 70%, 90% rationale stated, contaminated instruments listed by id.

## J3 Exception ruling (architect): Card E's script is ordinary analysis tooling, NOT a new evaluator/harness/runner.
Shape: ONE module `scripts/analysis/card_e_cli_vs_twc.py`, argparse only, no unit; pure `classify_mismatch(...)` + the T1/T2/Holm
arithmetic as pure functions with fixture tests (no network); Kalshi transport imported read-only from `scripts/analysis/k1_kalshi_prior.py`
(~865–940); IEM via `afos_cli_text_url` + `IemCliTransport` only — NEVER `iem_cli_fetch.fetch` (single writer of the prod cache); raw
text to the scratchpad; writes only `docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.{md,parquet}`.

## J4 Engine verdict §3 (H4): correct semantics (`engine.pyx` 4610–4727, 7010–7096) but incomplete — flipping 747/752 is inert for
makers until the order guard admits resting orders and `fees.py` is fixed; `liquidity_consumption=True` triggers
`_seed_trade_consumption`; pins to replace: `tests/unit/test_runtime_backtest_harness.py:583/586`, the docs parity test,
`BACKTEST_VENUE_CONFIG.md` rows 59/62 (§8 line 291 already says the False rationale expires). Card B's `queue_sizes` is a parallel
re-implementation of Nautilus queue arithmetic: descriptive prior only; the engine path is the mandatory successor if B survives.

## J5 Own-order set (H6): durable store order/intent records authoritative; manifests + node logs cross-checks; E and D-G0 only trim
denominators; REFUSE if the set cannot be built for A/LOW/C/B.

## J6 Relabel the Card E exception per J3 in design_r2 and prereg (H5). ## J7 Freeze the prereg sha only after J1–J3 (H7).
