# STRAT-DESIGN r2.1 — pre-registration, Run 1 = Card E only (2026-10-31)

Frozen before the run. Run 2 is not registered. Later cards are not started. Nautilus is not modified. `allow_short` stays false. No safety, settlement, contract, pin, or NO-SEND test is weakened. No daily budget, no per-position size, no live-trading enablement, no execution-egress change.

## 1. Hypothesis

One mechanism, M-basis: Kalshi names The Weather Company and publishes an integer °F settlement, while the rules name an NWS CLI station. The estimand is that degree-level gap versus the CLI calendar-day extremum (tmax on HIGH, tmin on LOW). Hourly-max, DST, and the amendment process are not mechanisms here. H0: each station-side-day mismatches with probability 1%. The alternative is a rate above 1%, pooled (T1) or on one side that also has a dominant sign (T2).

## 2. Data

Kalshi, public and unauthenticated, read-only through `KalshiHttp.list_series_markets` in `scripts/analysis/k1_kalshi_prior.py` (that file is not edited; a 401/403 is a stop, not an auth prompt). Endpoints: `markets` with `status=settled`, and `historical/markets`. Fields: `result`, `expiration_value`. Join on the climate date in `event_ticker` (the YYMMMDD token the event names), never on open, close, or expiration timestamps. No decodable event date: exclude the row. Do not guess.

IEM CLI via `afos_cli_text_url` and `IemCliTransport.fetch_cli_text` only. Never `iem_cli_fetch.fetch` and never a writer of the production CLI cache. Raw text goes to the scratchpad.

CLI pull timestamp, frozen: one pull per station. `pull_ts_utc` is the UTC time of the first request and is written into both artefacts before any mismatch is counted. Climate day 2026-10-30 may still be non-final on 2026-10-31; non-final text is excluded, not waited on. No second pull of this window.

Amendments and voids are excluded, not mismatches. A corrected or amended CLI product, or a day with no final integer, is excluded. A void or cancelled Kalshi market is excluded.

## 3. Station-sides and the LOW decision

48 sides: the 24 CLI stations in `docs/evidence/venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md` lines 17–40, HIGH and LOW. A missing series is missing, not replaced.

Frozen marginals from the availability pull (row counts only). n per side = days with both labels, computed once in the run. It is not the marginal. Cap = min(Kalshi, IEM). HIGH and LOW were not counted apart, so the two sides of one station may differ.

| Stations | Kalshi | IEM | n ≤ |
|---|---|---|---|
| 18: ATL AUS BOS MDW DFW DEN HOU LAS LAX MIA MSY NYC OKC PHL SAT SFO SEA DCA | 91 | 91 | 91 |
| PHX (Kalshi not in the short list; outside the 18 only because IEM is 89) | 91 | 89 | 89 |
| MSP | 90 | 91 | 90 |
| SAN | 71 | 90 | 71 |
| EWR, TTN | 65 | 91 | 65 |
| SDF | 63 | 91 | 63 |

LOW decision: tmin parser required; m stays 48. `CliLabel` (`scripts/analysis/settlement_alignment_study.py:111`) has `tmax_f` only. LOW is not scored with tmax. The script parses tmin from raw CLI text in pure functions with fixture tests and no network. It does not modify `CliLabel` or a production parser. A LOW day with no final tmin integer is a missing label. Dropping LOW (m = 24, Holm recomputed) is a different registration.

## 4. Mismatch

Mismatch = int(expiration_value) − CLI_final_int ≠ 0 at degree level; null/non-numeric expiration_value, void/cancelled markets and CLI amendments EXCLUDED (delete "amendments and voids are mismatches"); bucket-level check (`result` vs CLI-implied bucket) reported, not gated.

A non-integral number is non-degree: exclude it, do not truncate. `CLI_final_int` is tmax on HIGH and parsed tmin on LOW.

## 5. Rule

Two tiers. α split 0.025 + 0.025 (FWER ≤ 0.05).

T1. Pooled exact one-sided binomial on every frozen station-side-day, short sides included. p0 = 1%, α = 0.025. Critical k is the smallest k with P(X ≥ k | N, 0.01) ≤ 0.025, computed at the realized N. Anchor only, not the gate: ≈ k ≥ 54 at N ≈ 4080. At N = 4080 the exact gate is k ≥ 55 (P(X ≥ 54) = 0.0267). Power at a true 5% rate: 0.13 if 1 side is affected, 0.47 if 3, 0.90 if 6, ≈ 1 if ≥ 12. Not a reason to lower k.

T2. Per-side Holm over m = 48, family α = 0.025, exact one-sided binomial, p0 = 1%. Order sides by ascending p. Rank i rejects only if p ≤ 0.025 / (48 − i + 1) and every stronger rank rejects. Step-1 counts: k ≥ 6 at n = 90 and at n = 71; k ≥ 5 at n = 65 and at n = 63. Any other realized n uses this same test; the script computes that critical value. Not a new look. Per-side power at 5% ≈ 0.25–0.30. A single-station basis cannot be certified at these n.

Sign: a Holm-flagged side needs ≥ 80% of its mismatches in one direction (fraction ≥ 0.80). Direction is not fixed ex ante. The sign rule binds T2, not T1. Chronological half-split (first ⌊n/2⌋ matched days versus the rest) is reported for every side as a stability check only, never a gate.

## 6. PASS, KILL, INCONCLUSIVE

Exactly one card label:

- PASS = T1 rejects, or at least one side rejects under Holm and meets the sign rule.
- KILL = T1 does not reject AND the exact one-sided 95% upper confidence bound on the pooled rate is ≤ 2.0% (Clopper-Pearson: the 0.95 quantile of Beta(k+1, N−k)).
- INCONCLUSIVE = every other outcome.

n < 118 is not a label. Every station-side is exactly one of: PASS if that side Holm-rejects and the sign rule holds; KILL if it is not a side PASS and the card is KILL; INCONCLUSIVE otherwise.

## 7. What each outcome decides

PASS opens the Kalshi venue question as a build decision. It does not set a size, a budget, or a per-position cap, and it places no order. KILL closes the basis cell. INCONCLUSIVE names d*, the smallest count of extra pooled station-side-days which, added with zero mismatches, would bring that same upper bound to ≤ 2.0%. Days-to-PASS need a future rate and are not reported.

## 8. Entry

`scripts/analysis/card_e_cli_vs_twc.py` is a one-off analysis script. It is not a harness, not an evaluator, and not a runner. Argparse flags, and no others: `--scratchpad DIR` (raw Kalshi JSON and raw CLI text) and `--prereg PATH` (this file). It refuses to run while the sha256 line says PENDING. No `--truth`, no catalog, no auth, no alpha, no window, no station override. Pure `classify_mismatch(...)` plus the T1/T2/Holm arithmetic, with fixture tests that do not use the network. Writes only `docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.md` and `docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.parquet`, plus raw text under `--scratchpad`.

## 9. Multiple looks (L-34)

One look. The trigger is this rule on the one pull. No re-run on the same window. A second CLI pull, a second Kalshi pull, or a parser change after counts are seen is a new snapshot and is not authorized.

## 10. Leakage

The availability precheck saw row counts only. It did not see `expiration_value`, `result`, CLI integers, signs, or mismatches.

## 11. Freeze

Frozen inputs: stations file `docs/evidence/STRAT_DESIGN_2026-10-31/stations_card_e.json` sha256 89c6ed6a867078ff2fc5cc1eef58fc20e91c1c1ffff9f1445833b4bb1718ccba (24 rows, 48 sides). sha256 of THIS file is recorded, after commit, in `docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_e.txt` together with the freezing commit; the script must be passed that digest via `--prereg-sha` and refuse to run on mismatch. One look (L-34).

## 12. Prize (NON-BINDING)

Not a gate and not an input to any label. If a PASS is later sized, q stays unset: 137 × 0.02 = $2.74, and $1.93 after 84/119 on a PM.us leg only. $6.85 = 137 × 0.05 is the 5% alternative, not a floor. Kalshi fees are absent from that sketch.
