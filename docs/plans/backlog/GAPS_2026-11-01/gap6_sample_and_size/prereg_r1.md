# GAP-6 S0 and census preregistration r1 — frozen 2026-11-02

Authority: `docs/evidence/RULING_gap6_b8_d2_2026-11-02.md`; definitions from `plan_r1.md` + `plan_r2_delta.md` + `plan_r3_delta.md`, with the explicit clarifications below. S0 is SEARCH (FQ-R14), never confirmatory or a trade rule; α_K remains unspent. This freeze precedes S0 fetch, audit and the single verdict look.

## F-1 Population

48 series by `series_ticker` (24 `kalshi_high_series` + 24 `kalshi_low_series` from `docs/evidence/STRAT_DESIGN_2026-10-31/stations_card_e.json`), listed literally:

HIGH: KXHIGHTATL, KXHIGHAUS, KXHIGHTBOS, KXHIGHTDC, KXHIGHDEN, KXHIGHTDAL, KXHIGHTEWR, KXHIGHTHOU, KXHIGHTLV, KXHIGHLAX, KXHIGHCHI, KXHIGHMIA, KXHIGHTMIN, KXHIGHTNOLA, KXHIGHNY, KXHIGHTOKC, KXHIGHPHIL, KXHIGHTPHX, KXHIGHTSAN, KXHIGHTSATX, KXHIGHTSDF, KXHIGHTSEA, KXHIGHTSFO, KXHIGHTTTN.

LOW: KXLOWTATL, KXLOWTAUS, KXLOWTBOS, KXLOWTDC, KXLOWTDEN, KXLOWTDAL, KXLOWTEWR, KXLOWTHOU, KXLOWTLV, KXLOWTLAX, KXLOWTCHI, KXLOWTMIA, KXLOWTMIN, KXLOWTNOLA, KXLOWTNYC, KXLOWTOKC, KXLOWTPHIL, KXLOWTPHX, KXLOWTSAN, KXLOWTSATX, KXLOWTSDF, KXLOWTSEA, KXLOWTSFO, KXLOWTTTN.

## F-2 Window

Climate day ∈ [2025-07-01, 2026-07-01); rows outside are dropped before any non-identity field is read.

## F-3 Rows

Finalized yes/no only; exclusion mirrors card_e `_row_exclusion` (cancelled → void → not_finalized), each counted.

## F-4 NO ask

NO ask = 1 − yes_bid.close (Decimal); missing or outside (0,1) exclusive ⇒ excluded + counted; YES ask never used. `_candle_decimal(node, "close")` reads the historical `close` and live `close_dollars` schemas from `yes_bid`.

## F-5 Tail band

NO ask ∈ [0.97, 0.99] inclusive.

## F-6 Excess

excess = 1{result == "no"} − NO ask; θ = 0.

## F-7 Cells

{HIGH, LOW} × {pre, post}; only the 2 pre cells gate.

## F-8 Reference hours

Reference hours (LST) exactly as r1 §4: HIGH pre = {D-1 open-hour, D 10:00}, post = {D 17:00}; LOW pre = {D-1 open-hour, D-1 18:00}, post = {D 10:00}.

Verified quotation from `plan_r1.md` §4:

> **Reference hours (local standard time).** Hours not listed are "intra" and reported only.

| Side | Pre | Post |
|---|---|---|
| HIGH | D-1 open-hour; D 10:00 | D 17:00 |
| LOW | D-1 open-hour; D-1 18:00 | D 10:00 |

## F-9 LST table

Literal 48-row series → (station, std UTC offset hours) table. Computed with `/home/jon/breezy/.venv/bin/python` from each station JSON `tz`: `datetime(2026, 1, 15, 12, tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).utcoffset().total_seconds() / 3600`. These fixed standard offsets apply throughout; unknown series ⇒ raise; no default. Identity comes from `series_ticker`, never ticker parsing.

| Series | Station | Standard UTC offset (hours) |
|---|---|---|
| KXHIGHTATL | KATL | -5 |
| KXLOWTATL | KATL | -5 |
| KXHIGHAUS | KAUS | -6 |
| KXLOWTAUS | KAUS | -6 |
| KXHIGHTBOS | KBOS | -5 |
| KXLOWTBOS | KBOS | -5 |
| KXHIGHTDC | KDCA | -5 |
| KXLOWTDC | KDCA | -5 |
| KXHIGHDEN | KDEN | -7 |
| KXLOWTDEN | KDEN | -7 |
| KXHIGHTDAL | KDFW | -6 |
| KXLOWTDAL | KDFW | -6 |
| KXHIGHTEWR | KEWR | -5 |
| KXLOWTEWR | KEWR | -5 |
| KXHIGHTHOU | KHOU | -6 |
| KXLOWTHOU | KHOU | -6 |
| KXHIGHTLV | KLAS | -8 |
| KXLOWTLV | KLAS | -8 |
| KXHIGHLAX | KLAX | -8 |
| KXLOWTLAX | KLAX | -8 |
| KXHIGHCHI | KMDW | -6 |
| KXLOWTCHI | KMDW | -6 |
| KXHIGHMIA | KMIA | -5 |
| KXLOWTMIA | KMIA | -5 |
| KXHIGHTMIN | KMSP | -6 |
| KXLOWTMIN | KMSP | -6 |
| KXHIGHTNOLA | KMSY | -6 |
| KXLOWTNOLA | KMSY | -6 |
| KXHIGHNY | KNYC | -5 |
| KXLOWTNYC | KNYC | -5 |
| KXHIGHTOKC | KOKC | -6 |
| KXLOWTOKC | KOKC | -6 |
| KXHIGHPHIL | KPHL | -5 |
| KXLOWTPHIL | KPHL | -5 |
| KXHIGHTPHX | KPHX | -7 |
| KXLOWTPHX | KPHX | -7 |
| KXHIGHTSAN | KSAN | -8 |
| KXLOWTSAN | KSAN | -8 |
| KXHIGHTSATX | KSAT | -6 |
| KXLOWTSATX | KSAT | -6 |
| KXHIGHTSDF | KSDF | -5 |
| KXLOWTSDF | KSDF | -5 |
| KXHIGHTSEA | KSEA | -8 |
| KXLOWTSEA | KSEA | -8 |
| KXHIGHTSFO | KSFO | -8 |
| KXLOWTSFO | KSFO | -8 |
| KXHIGHTTTN | KTTN | -5 |
| KXLOWTTTN | KTTN | -5 |

Five shared PM.us station offsets match k1's registry-backed `offset_hours_for_series` (verified by direct calls): KXHIGHNY → KNYC (NYC) = -5; KXHIGHMIA → KMIA (MIA) = -5; KXHIGHCHI → KMDW (MDW) = -6; KXHIGHLAX → KLAX (LAX) = -8; KXHIGHTSFO → KSFO (SFO) = -8 hours.

## F-10 D-1 open-hour

D-1 open-hour = first whole LST hour starting ≥ open_time (a start exactly on the hour counts); ref_end = hour start + 1 h; valid only if is_pre_climate_day(ref_end as epoch ns, climate_day, std offset).

## F-11 Exact-end rule

Use only the hourly candle with end == ref_end; end < ref_end ⇒ miss (counted per cell); end > ref_end ⇒ refused as look-ahead; no carry-forward. Supersedes r2 R2-1 "END ≤ ref" as a prereg clarification.

## F-12 Look-ahead asserts

**F-12 Look-ahead asserts.** Let D be the climate day and W the observation-window start, in LST using the F-9 fixed offset. HIGH: W = D 10:00 LST, the start of the daytime heating period in which the day's maximum forms. LOW: W = D 00:00 LST, the start of the climate day and of the overnight-minimum period. Asserts, each raising on violation: (a) ref_end < settlement; (b) for every pre-cell reference, ref_end ≤ W, so the candle ending at W is the latest admissible, which gives D-1 open-hour and D 10:00 for HIGH, and D-1 open-hour and D-1 18:00 for LOW; (c) for every post-cell reference, ref_end > W (reported only). Post cells never gate. Rule (b) is '≤' because the HIGH D 10:00 pre reference has ref_end exactly equal to W.

## F-13 Fetch is not a look

Sealed per-series raw files (create-exclusive) + one MANIFEST.sha256 when all 48 present; INCOMPLETE ⇒ resumable; only `verdict` is the look and runs once (refuses if S0_<date>.json exists).

## F-14 Unit (L-40)

n = distinct station-days per cell with ≥5 distinct climate days; cell statistic = mean over station-days of the within-station-day mean excess (station-day weighted). Clarification of r1 §5 (which did not define the unit). r1's pooled mean over all tail-band observations is ALSO reported. KILL-concordance: KILL requires BOTH the station-day-weighted mean ≤ 0 AND the pooled mean ≤ 0 in both pre cells; disagreement ⇒ INCONCLUSIVE.

## F-15 Decision and descriptive intervals

KILL iff both pre cells adequate and both satisfy F-14 concordance (futility rule on point means); CONTINUE iff either the weighted or pooled mean > 0 in any pre cell, or INCONCLUSIVE; descriptive only: day-cluster bootstrap (iterations=2000, seed=20261102 literal) and wilson_interval on NO-win counts.

## F-16 Post cells

Post cells never enter the gate; summarize_stratum is not used; no verdict string reaches the gate.

k1 `break_even_probability`, `wilson_interval`, `summarize_stratum` are imported and identity-tested only; `summarize_stratum` is not called in the gate.

## F-17 Adequacy

n ≥ 30 station-days and ≥ 5 days else INCONCLUSIVE (carried from r1; futility-screen floor, not a power claim); thin listing history ⇒ INCONCLUSIVE ⇒ CONTINUE; per-station n reported in the audit.

## F-18 Predicted floor

Fixed here from r1 §7 and its following tail-cell arithmetic: "edge ≤ 1 − ask ≤ 3¢ gross" and "likely ≈ 0 or negative" after the fee (`plan_r1.md`, line 156). Numeric gross ceiling = 0.03 per contract; predicted after-fee floor ≈ 0 or negative. The 3¢ value is an upper bound, not a positive lower bound or a power claim.

## F-19 Endpoint semantics from P-0

F-19 decision: For hourly candles in both schemas, `end_period_ts` is the bucket END of (end−1 h, end]; market opening is `markets[].open_time`. Use the candle only when `end_period_ts == ref_end`, reading historical `yes_bid.close` or live `yes_bid.close_dollars` through `_candle_decimal`; no carry-forward. Mismatch found at S3b ⇒ HALT to peer loop, no verdict.

Source: `docs/evidence/kalshi_depth/P0_candle_semantics_2026-11-02.md`; committed fixture evidence, 0 network GETs.

## F-20 Census constants (row #6, frozen now)

One-sided α 0.025, z 1.96 + 0.84, σ 0.14, δ 0.02, n_req 385, H 120 d, D_gate 1, depth grid {1, 10, 100}.

## F-21 Output

On KILL the script writes `ADAPTER_DECISION: NO-GO` into S0_<date>.md, only on KILL; coordinator notes go in a separate sidecar; the prereg's sha256 is pinned in the script as FROZEN_PREREG_SHA (no sidecar sha file).

Verdict outputs are written to docs/evidence/kalshi_depth/S0_<date>.{md,json}; the audit to docs/evidence/kalshi_depth/S0_<date>_audit.md.

S3 procedure: S3a fetch+seal (one-series timing probe first; RuntimeMaxSec ≥ 1.75× projection; MemoryMax=2G; LimitNOFILE=524288; stall watch) → S3b outcome-blind audit (audit_projection drops `result`; reports per-cell/per-station n, misses, exclusions, F-19 consistency) → S3c verdict from sealed raw only.
