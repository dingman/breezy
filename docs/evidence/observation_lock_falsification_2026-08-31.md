# Observation-Lock Strategy Falsification — Archive-Powered Evidence

Generated: 2026-08-31
Data: held AFOS archive `~/.local/share/breezy/archive/settlement-alignment-cache/`
(2020-12..2026-08, ~1,835 station-days/site x KNYC/KMIA/KMDW/KLAX/KSFO), with the
live catalog replacing overlapping rows.
Archive admissibility: validation bridge PASSED — 36 overlapping final records,
0 mismatches (`docs/evidence/settlement_alignment_2026-08-25.md`).

Scope: falsification only. No prices were reconstructed for expired markets; the
economic overlay in the briefs is NOT computed here.

---

## 1. `cli_settlement_print_lock` — both pre-registered gates PASS

Metric definitions matter. `p_stable` is measured on the FIRST FINAL (the morning
CLI that IS the settlement source), not on the first record of any kind.

| Metric | Threshold | Measured | N | Verdict |
|---|---|---|---:|---|
| `p_stable` (first final -> last pre-settlement) | >= 0.97 | **99.989%** | 9106 | PASS |
| Halt-window hit rate (>= 2.0h to 08:00 ET) | >= 0.20 | **98.66%** | 9164 | PASS |

Halt threshold is the REAL configured value: `min_hours_to_settlement = 2.0`
binds above `halt_hours_before_settlement = 1.0` (`risk.py`).

**Brief prediction REFUTED:** the brief predicted PT stations (KLAX/KSFO) "may
have no legal window". Both clear the gate comfortably.

Counter-metric, for contrast: including PRELIMINARIES, first-record stability is
only 92.82% (8466/9121). That is a different product describing an incomplete
day, and it is `running_extreme_lock`'s risk, not this strategy's.

## 2. `running_extreme_lock` — open tail PASSES, interior is DEAD on 3/5 sites

Directional survival (the open tail only loses on a DOWNWARD crossing):

| Scope | p_hold | N | Downward |
|---|---:|---:|---:|
| Pooled, all preliminaries | **99.7946%** | 9736 | 20 |
| Pooled, afternoon 15-17 local | 99.7880% | 8017 | 17 |

Threshold from the brief: dead if `p_hold < 0.96`. PASS with wide margin.

**Brief prediction REFUTED:** no monotonic improvement with later issuance hour
(already 99.83% at 16:00, dips at 17:00, recovers at 18:00).

### Margin-conditioned survival (this is the shape the decision must use)

A flat `min_p_hold` gates a margin-conditional hazard, and the strategy fires at
margin ~= 0 — the worst-conditioned cell.

| margin_f | p_hold | Wilson 95% lower |
|---:|---:|---:|
| 0 | 99.7946% | 99.6829% |
| 1 | 99.9076% | 99.8244% |
| 2 | 99.9486% | 99.8798% |
| 3 | 99.9692% | 99.9094% |
| 4 | 99.9897% | 99.9418% |
| 5 | 99.9897% | 99.9418% |

Downward events by magnitude: -1F x11, -2F x4, -3F x2, -4F x2, -16F x1.

### Acknowledged fat tail (NOT engineerable away)

MDW 2021-12-30: preliminary `MAXIMUM 55  7:11 AM`, final `MAXIMUM 39  MM`.
Neither product carries CCA/CCB or correction text; cached hourly observations
top out at 39.2F. An UNFLAGGED bad preliminary. `correction_flag` would not have
caught it and no margin guard band stops it. 1 in 9736.

## 3. Pre-registered prelim->final revision study — G-01 SUPERSEDED

Re-ran `scripts/analysis/preliminary_final_revision_rate_study.py`'s
pre-registered decision rule (N >= 90/site; per-site PASS = Wilson 95% UPPER
<= 0.05) against the archive. The 2026-08-26 run used the live catalog only
(`Archive data used: no`) and returned UNDERPOWERED at N=44.

| Site | N | Revisions | Rate | Wilson upper | Verdict |
|---|---:|---:|---:|---:|---|
| LAX | 1810 | 24 | 1.33% | 0.0197 | PASS |
| MDW | 1827 | 255 | 13.96% | 0.1562 | FAIL |
| MIA | 1819 | 67 | 3.68% | 0.0465 | PASS |
| NYC | 1823 | 215 | 11.79% | 0.1336 | FAIL |
| SFO | 1800 | 81 | 4.50% | 0.0556 | FAIL |

**Verdict: POWERED, and FAIL.** G-01's "UNDERPOWERED, no PASS claim is valid" is
superseded by a STRONGER constraint, not a release.

### Reconciliation with p_hold = 99.79% (these do NOT conflict)

Over the same 9736 preliminary records:

    unchanged 9070 | UP 646 | DOWN 20
    any-change rate 6.84% | 97.00% of changes are UPWARD | downward 0.21%

The pre-registered rule measures SYMMETRIC change. The open tail only loses on a
downward crossing. A running max rising after the afternoon issuance is
physically expected, not a data defect.

**Consequences:**
- Open-tail path: SURVIVES. Ship `open_tail_only=True`.
- Interior-bucket path: DEAD on MDW, NYC, SFO — it requires exact equality.
- `cli_settlement_print_lock`: UNAFFECTED (trades the final, not the preliminary).

## 4. `stale_observation_hours` — derived, not guessed

The bound is a LIVENESS / feed-outage detector, not a decay model.

Preliminary -> first-final ISSUANCE lag (hours), archive:

| Site | N | P50 | P99 | max |
|---|---:|---:|---:|---:|
| LAX | 1810 | 7.23 | 10.60 | 11.38 |
| MDW | 1827 | 8.93 | 9.75 | 10.50 |
| MIA | 1819 | 12.00 | 12.32 | 15.98 |
| NYC | 1823 | 9.63 | 10.95 | 17.88 |
| SFO | 1800 | 7.98 | 8.32 | 18.80 |
| POOLED | 9079 | 8.75 | 12.17 | 18.80 |

Live steady-state issuance -> receipt lag, pooled: P99 = 0.349h (N=79).

**Recommended `stale_observation_hours` = 12.665h**, as max-over-sites P99
(MIA 12.3167) + receipt P99 (0.3488).

NOT the pooled P99 (12.17 + 0.35 = 12.52): MIA's own P99 exceeds the pooled P99,
so a pooled bound would spuriously refuse MIA's slowest ~1% of LEGITIMATE days.

Caveats: observed MAX issuance gap is 18.80h, so even a P99-derived bound fires
on rare legitimate days. The live receipt sample is N=79 and steady-state only —
the all-live figure of 179.6h is dominated by recovery backfill and MUST NOT be
used. The archive has no Breezy receipt-time analogue. The archive reader
reported 6 `ArchiveRefusalError` rows.

---

## What this evidence does NOT establish

- No economic/edge overlay: in-life `OrderBookDepth10` asks were not joined to
  these signals. Every gate above is settlement-side only.
- Wilson bounds assume independent Bernoulli trials; product errors may cluster,
  which would understate uncertainty.
- The candidate-tail-floor sweep used in the margin analysis is a documented
  PROXY (every integer in `[H-5, H]`), because historical Polymarket bucket
  listings are unavailable. Coverage-cost percentages from that sweep are an
  artifact of the proxy and must not be read as economic coverage.
