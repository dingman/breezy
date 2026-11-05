# Decision funnel: 100% of decisions die upstream of pricing

**Date:** 2026-09-20 · **Source:** `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_<date>.jsonl`
**Status:** MEASURED, not inferred. Read-only over the live tape; the node was not signalled.

## The funnel

| Stage | 2026-09-20 | 2026-09-16 |
|---|---|---|
| Decisions emitted | 40,796 | 53,624 |
| Rung resolved (not `observation_ambiguous`) | 4,816 (12%) | 276 (0.5%) |
| Cell legal (not `illegal_cell`) | **0** | **0** |
| Reached a price (`ask` and `break_even` both set) | **0** | **0** |
| Margin > 0 | 0 | 0 |
| Orders | 0 | 0 |

`ask`/`break_even` are populated by `_finalize_take` only at the
`edge_below_break_even` refusal or a `Take`. They are `None` on **every row of
every day recorded**. On the two days measured here (2026-09-20 and
2026-09-16 -- both after the last fill, 2026-09-15T20:12:06Z), no decision
reached the pricing gate. That is this table's measurement, not a claim about
any other day (AUD-16a).

## Gate 1 — `observation_ambiguous` (35,980 rows; MIA, LAX)

`RunningMax.value_at` (`src/breezy/strategy/weather_common/running_extreme.py:286-297`)
sets `exact_f` only when the maximizing row `is_metar`. A non-METAR integer-°C
observation of 31 °C means the true value lies in [30.5, 31.5) °C = [86.9, 88.7) °F,
stored as the closed interval `[87, 89]`. `RunningMax.spans` (`:172-202`) then
refuses whenever the two endpoints index different rungs — which a 2 °F ladder
makes essentially certain.

Observed band widths today: 1 °F × 30,254, 2 °F × 5,726. Sample MIA interval
`lower=87, upper=89`.

**This gate is correct, not defective.** Verified: all 1,968 rows with
`running_max_exact = True` resolved a rung and passed this gate; every one of the
35,980 `observation_ambiguous` rows was non-exact.

### Why the rows are non-exact (ROOT CAUSE, verified in source AND data)

METAR rows are PRESENT and CORRECTLY FLAGGED at all four stations. The parser
works. They lose the running max to their own coarse companions.

NWS serves two feeds per station: hourly METARs at tenths °C
(`precision_c_tenths=5`, non-empty `rawMessage`) and a 5-minute feed at whole °C
(`precision_c_tenths=10`, empty `rawMessage`). `value_at` selects the maximizing
row by `_sort_key = (row.upper_f_closed(), row.is_metar, observed_at_ns)` — the
TOP of each row's uncertainty interval — and sets `exact_f` only if that winning
row is a METAR.

| row | interval °C | interval °F | exact |
|---|---|---|---|
| MIA METAR 31.7 °C | [31.65, 31.75] | `[89, 89]` | yes |
| MIA 5-min 32 °C | [31.50, 32.50] | `[89, 90]` | **no** |

The coarse row reaches higher, wins, and `exact_f` becomes `None`. The resulting
band is width 1 — which independently explains the 30,254 width-1 bands measured
above. Two separate measurements agree.

Per-station running max, 2026-09-20 (tenths °C):

| station | final max | METAR-only max | max set by METAR? | rungs resolved? |
|---|---|---|---|---|
| MIA | 320 | 317 | no | no |
| LAX | 260 | 250 | no | no |
| MDW | 220 | 217 | no | no |
| SFO | 172 | 172 | **yes** | **yes** |

SFO escaped only by arithmetic luck: 16.7 °C rounds DOWN to 17.0, which does not
exceed the METAR's own upper bound. It is the one station whose max was set by a
METAR and the one station that resolved rungs.

**The estimator is EPISTEMICALLY CORRECT.** With a whole-degree 5-minute feed the
bot genuinely does not know the running max to better than ±0.5 °C. A fix that
merely "prefers METAR" would narrow an interval the data does not support,
manufacturing false confidence in the exact quantity that gates real money. The
real options are a change to the ESTIMAND (R(t) over METAR rows only — class-C
PREREG, settlement-alignment risk) or a change to the DATA (a genuinely
sub-degree high-cadence feed). Both are under design review.

## Gate 2 — `illegal_cell` (6,640 rows; SFO only)

Every single one is `width_code == 2` = `open_lower`, the open-ended bottom tail
rung, which `_is_legal_cell` (`src/breezy/strategy/current_rung_hold/decision.py:291-302`)
refuses unconditionally: `return (width_code == 0 and m_code == 0) or width_code == 1`.

SFO's observations *are* exact (2,028 METAR rows). They simply resolve to a rung
that policy never trades. Confined to hours 12-13 LST. MDW produced zero
decisions all day.

## Consequences

1. **The fee fix did not unblock trading.** θ drift 0.06→0.0695 (09-17) was the
   *second* blocker. 09-16, before the drift, was already zero-priced for Gate 1.
   Registering `pm_us_crh_v4` removed a real blocker and returned the bot to its
   prior zero-trade state. This corrects the working narrative of 09-17..09-20.
2. **HUNT-1 (widen the 12-17 LST window) is moot.** It was already shown no hour
   clears zero ask-relative edge (`ALL_HOURS_EDGE_TABLE_2026-09-20.md`); it is now
   shown no hour reaches a price at all. Widening the window cannot produce a take
   while both gates hold. HUNT-1 stays open but is de-prioritised behind these two.
3. **"Why no trades" is answerable in seconds and was not being asked.** The tape
   has carried the answer since 09-16. The diagnosis gap recorded on 09-14 was
   never closed — see `docs/core/LESSONS.md` and the monitoring proposal below.

## Monitoring implication

Every existing signal is a *fault* signal (something broke) or a *wait* signal
(nothing to do). None is an *edge* signal. "Zero trades" currently reads
identically whether the bot refused at margin −0.001 or never looked at a price.
The funnel above is the minimum daily digest, and it must be DELIVERED (ntfy
egress, proven working 09-20) rather than written to a file nobody opens — the
failure mode this session already paid three days for.

## Open questions dispatched

- RESOLVED: METAR is present at all four stations and correctly flagged. The coarse
  whole-degree companion row outranks it in the running max. See root cause above.
- Why did MDW produce zero decisions? NOT an observation problem — 298 rows stored,
  normal shape. Cause lies elsewhere (market listing / instrument availability).
- The observation store begins 2026-09-17; the 09-16 symptom CANNOT be verified
  against stored observations.

## Candidate fixes under review (2026-09-20)

**Option A — change the estimand.** Restrict `RunningMax.value_at`'s candidate
rows to `is_metar=True`. Confined to `running_extreme.py:265-305`; no new
ingestion. Recommended by design review, WITH its own strongest objection stated:
a METAR-only R(t) can under-report a true intraday max landing between hourly
METARs, biasing low in exactly the hours the strategy trades. Blast radius ~27
callers, ~9 test files. Design review judged this a **class-C PREREG reset**
(n reset, fresh alpha) because it changes which observations define R(t).
It also DISCARDS information: the coarse rows do genuinely constrain the max.

**Option B — live sub-degree feed via IEM `asos1min.py`.** REJECTED on evidence.
The 1-minute archive schema is `station,station_name,valid(UTC),tmpf,dwpf` with
`tmpf` an INTEGER whole degree FAHRENHEIT and no `metar` column — sub-degree-C
but NOT tenths. `iem_asos_rows_to_station_observations` reads `row["metar"]` and
would drop every row.

**Option C — wire the IEM MADIS 5-minute METAR stream (NEW, found 09-20).**
`scripts/analysis/settlement_alignment_study.py:408-433` `asos_url()` builds an
IEM `asos.py` request with `report_type=1&report_type=2` = the MADIS 5-MINUTE
METAR/SPECI text stream, carrying tenths via the T-group. Already fetched daily
by `asos_recent_refresh.py` through the offer-gate and mb-daily units; **never
wired to the trading node.** Cached proof of recency
(`~/.local/share/breezy/archive/settlement-alignment-cache/`, written 09-20 02:06):

```
LAX,2026-09-20 01:50,KLAX 200150Z AUTO 26011KT 10SM 22/17 A2990 RMK T02200170 MADISHF
```

5-minute cadence AND tenths precision. This REPLACES the coarse rows rather than
discarding them, so it dissolves the between-METAR objection to Option A, and it
plausibly needs no estimand change (the decision rule is untouched; only data
precision improves) — though whether that still trips class-C is a review call,
not a unilateral one.

Cost: a new live ingest actor mirroring `NwsIngestActor`, wired through
composition and the settlement gate. Third-party dependency on IEM. Observed lag
16-40 min vs `NWS_API_ASSUMED_PUBLICATION_LAG_NS` = 21 min and
`DEFAULT_STALENESS_BOUND_SECONDS` = 3_000. **Option C trades latency for
precision and that tradeoff must be measured, not assumed.**

Two measurements are in flight to decide between A and C: (1) would METAR-only
R(t) actually resolve rungs, computed with the repo's OWN `RunningMax`/`spans`;
(2) the size of the between-METAR under-reporting gap against the 5-minute
tenths stream.

## RULING: Option A is REJECTED on measured evidence (2026-09-20)

Two INDEPENDENT measurements, different methods, different data, same answer.

### Measurement 1 — replay of the repo's OWN `RunningMax`

784 decision instants, 4 stations x 4 climate days (09-17..09-20), 5-min grid
12:00-16:00 LST. Ladder read from real venue instruments via
`read_weather_bucket_facts`. Option A emulated by pushing only `is_metar=True`
rows into the real accumulator.

- Decisions reaching the pricing gate: 514/784 (65.6%) -> **784/784 (100%)**.
- **But the gate is removed BY CONSTRUCTION, not satisfied.** METAR-only rows
  collapse the interval to a point (`lower_f == upper_f == exact_f`), so
  `spans()` on a tiling ladder can never refuse. Exactness is structural.
- **Counter-measurement: at 150/784 instants (19.1%) the Option-A point value
  lies strictly BELOW the status-quo `lower_f`** — the discarded coarse rows
  PROVE the day's max was already 1-4 °F higher (worst MDW 09-17: 4 °F;
  MIA 09-19: 3 °F). Never above.

Trading a 34.4% refusal rate for a 19.1% rate of confidently resolving onto a
demonstrably-wrong rung is strictly worse than refusing.

### Measurement 2 — 5.7 years of MADIS 5-minute cache

Ground truth: `~/.local/share/breezy/archive/settlement-alignment-cache/*.txt`,
224 files, MADIS 5-minute METAR/SPECI with tenths T-groups, parsed with the
repo's own `parse_metar_t_group` / `round_half_up_f`. 7,117 station-days,
348,733 instants, 2020-12-31 -> 2026-09-20, LAX/MDW/MIA/SFO.

(5-min-derived R(t)) − (hourly-METAR-only R(t)), °F:

| stn | station-days | mean | med | p90 | p99 | max |
|---|---|---|---|---|---|---|
| LAX | 1,777 | 0.848 | 1 | 2 | 3 | 7 |
| MDW | 1,748 | 0.843 | 1 | 2 | 3 | 13 |
| MIA | 1,796 | 0.874 | 1 | 2 | 3 | 5 |
| SFO | 1,796 | 1.006 | 1 | 2 | 5 | 14 |
| **POOL** | **7,117** | **0.893** | 1 | 2 | 4 | 14 |

- `>=1 °F` at **59.6%** of instants; `>=2 °F` (a FULL RUNG) at **22.4%**.
- Worst exactly in the trading hours: 12 LST mean 1.012 °F, >=2 °F 26.8%;
  decaying to 16 LST mean 0.761 °F, >=2 °F 17.5%.
- Never negative (0.0000) — the expected one-sided-bias consistency check passes.
- Adding SPECIs barely helps: pooled mean 0.863, >=2 °F 0.213.

### Convergence

Method 1 (784 instants, 4 days, real `RunningMax`) says 19.1% of instants resolve
too low. Method 2 (348,733 instants, 5.7 years, MADIS cache) says 22.4% are >=2 °F
low. Two different data sources and two different techniques agree to within ~3
points. **Option A is rejected.**

### Honest limits carried forward

- Instants are heavily autocorrelated within a day; effective n is nearer the
  7,117 station-days than 348,733 instants. The >=2 °F figure is a per-instant
  rate, not a per-day-independent one.
- 0.89 °F is a LOWER BOUND on the gap to a true instantaneous max — the 5-minute
  stream is itself a sample, not the continuum.
- Measurement 1's n is small: effectively 12 solid station-days, one venue week,
  one season. 09-16 unusable (no observations stored), 09-18 fragmentary.
- Neither method was scored against settlement truth (CLI `tmax_f`); that join
  was not performed.
- NYC has NO 5-minute stream in cache; the result does not transfer there by
  measurement, only by analogy.

### Consequence

**Option C is the surviving candidate** — replace the coarse rows with the
tenths-precision 5-MINUTE stream, which is exactly the data Measurement 2 used as
ground truth. The decisive open question is whether that stream is available LIVE
at acceptable latency (observed 16-40 min). Design plan in flight; mandatory
adversarial peer review to follow, to include `prediction-market-reviewer`.

## RULING: Option C is REJECTED AS SPECIFIED; viable only after redesign (2026-09-20)

Mandatory planning-gate peer review, three independent reviewers.

### Latency-tail hypothesis: REFUTED (coordinator's own hypothesis was wrong)

Measured with the REAL venue ladder (parsed from captured `binary_option`
instruments via `parse_weather_slug` + `assert_bounds_cross_checked`; e.g.
KMIA 09-19 `[<=83],[84,85],[86,87],[88,89],[90,91],[>=92]`):

| L (min) | exact | spans-refusal | coarse-row wins |
|---|---|---|---|
| 0 (bound) | 100.0% | 0.0% | 0.0% |
| 15 | 65.6% | 13.5% | 34.4% |
| 30 | 56.9% | 17.9% | 43.1% |
| 40 | 52.8% | 19.9% | 47.2% |
| 60 | 44.6% | 24.5% | 55.4% |
| **status quo (NWS only)** | **0.8%** | **50.5%** | **99.2%** |

The tail is real (coarse row wins 34-47% of instants at observed lag) but does
NOT defeat the design: against TODAY rather than against L=0, lagged IEM cuts
refusals ~2.5-3.7x. Every coarse win had an IEM partner that had merely not
arrived (`coarse_wins_iem_lagged_out == coarse_wins`, zero missing-row cases), so
the measured loss is attributable to latency alone.

**Power caveat, decisive:** n is effectively **8 station-days**, not 392 instants.
Per-station-day refusal spans 0.0%-51.0%; the pooled 17.9% averages a BIMODAL
set and should be read as +/-25 points, not a standard error. Two of eight days
carry nearly all refusals. Refusal depends on whether the day's max sits near a
rung boundary — a property of the DAY, not the feed.

### Architecture review: REJECT as specified

1. **[CRITICAL] The intersection has nowhere to live.** `_rows` is
   `dict[int, _Row]` keyed by `observed_at_ns` (`running_extreme.py:222,258`); a
   second same-instant push OVERWRITES, documented as intentional (`:233-237`).
   Two actors on one accumulator = last-writer-wins, ordered non-deterministically
   by poll timing. There is never a pair to intersect. This is a STORAGE-MODEL
   change, not a fold change. The plan admitted it never read the fold body.
2. **[CRITICAL] No supersession rule.** Same-channel re-push is a CORRECTION
   (must replace); cross-channel same-instant is EVIDENCE (may intersect).
   Conflating them can intersect a correction with the row it supersedes ->
   empty set -> permanent fail-closed ambiguity.
3. **[HIGH] Per-source latency handling is a no-op as written.**
   `assumed_publication_lag_ns` is provenance, "used nowhere"
   (`observation_composition.py:19`, `nws_observation_config.py:76-78`). The
   decision path has ONE global `staleness_ns()` (`:307-323`) consumed by
   `observation_refusal` (`refusals.py:104`) — no per-source seam exists.
4. **[HIGH] Intersection is DIRECTIONALLY unsafe.** It can only raise a
   per-instant lower bound, so `lower_f` moves only UP, onto hotter rungs — in a
   MAXIMUM-temperature market, i.e. the trade direction. Validity requires proof
   the two feeds are the same sensor reading at the same instant differing only
   in rounding.
5. **[HIGH] Fail-closed disjointness is a regression vector.** At instants where
   NWS alone resolves today, a disjoint IEM partner newly refuses. Adding a
   source can LOWER the pass rate. Unbounded.
6. **[MEDIUM]** Blast radius 27 callers incl. `paper_replay`, `backtest_feed`,
   `position_monitor`, `exit_window_core`, and the replay-equivalence contract
   test. Every PREREG/calibration artefact built on the old R(t) becomes
   non-comparable.
7. **[LOW]** A new outbound host must be reconciled with the bwrap no-egress gate
   and the live node's NO-SEND policy before any transport lands.

The measurement implemented intersection OUTSIDE the accumulator, so it shows
what a CORRECT build would achieve, not what today's storage model does — which
confirms defect 1 is a build precondition. It also resolved 3 empty intersections
by keeping the IEM point, which is NOT fail-closed and biases the numbers
optimistically.

### Domain / market review: APPROVE WITH CHANGES

- Settlement stays CLI-based (`SettlementSite`, `registry/sites.py:96-117`); IEM
  is not spliced into settlement. But IEM-vs-CLI-final basis risk is UNMEASURED,
  unlike the METAR-vs-hourly gap, and must be quantified before an IEM-sourced
  `exact_f` is trusted as trade-grade.
- **EXPECTANCY: "Plausibly more volume, not demonstrated edge."** Nothing in this
  change touches pricing, forecast, or rung selection — it only converts
  refusals into pricing-gate-eligible decisions. Against the TERMINAL finding
  that market resolution prices ~1.98x tighter than the forecast, this may
  simply expose MORE trades to an already-closed edge.
- **Binding requirement: an EV gate on the newly-unlocked decisions BEFORE this
  is allowed to raise live order volume.**

### PREREG class: (C), on a corrected citation

The coordinator had been citing "L-34: a change to the registered ACTION or
estimand is class-C". **That is a misquote.** Real L-34 (`LESSONS.md:1290`) is
"The trial's TRIGGER is pinned; a re-look is a second snapshot". Its mechanical
test: *name the datum the registered rule selects; name the datum the proposed
path would feed the same test; if they can differ on any afternoon, it is class
(C)*. Option C changes that datum on essentially every afternoon => **class (C)**.
Both reviewers independently agree the class is right; the architecture review
adds that the rationale should be "decision-function change", not
selection-effect. No A/B/C taxonomy section exists in `LESSONS.md`.

### Consequence

Option C is MECHANICALLY VIABLE but is NOT approved to build. Preconditions:
defects 1-5 resolved in a revised design; IEM-vs-CLI basis risk measured; an EV
gate on newly-unlocked decisions; and the n=8 power problem fixed. A powered
re-measurement is in flight, synthesising the coarse feed by rounding the 5.7-year
MADIS tenths stream to whole °C (validated against real NWS coarse rows on the 8
overlapping station-days), with fail-closed empty-intersection semantics and
station-day-clustered bootstrap CIs.

## Day-end state, 22:43Z

Node PID 2953531, 5h53m uptime, ZERO fatals, log fresh. Permit verified from the
boot line (not assumed): `live-trading permit issued ... ttl_s=36000`, issued
16:50:29Z, expires 02:50:29Z — valid.

**51,398 decisions. STILL ZERO reached pricing.** `observation_ambiguous` 42,820
(83%), `illegal_cell` 8,578 (17%). The funnel is stable across the whole session.

### NEW open defect: two of four stations are not hunting

| station | decisions | LST now | in window [12,17)? |
|---|---|---|---|
| SFO | 15,418 | 14:43 | yes — evaluating |
| MIA | 35,814 (frozen) | 17:43 | no — window closed, expected |
| LAX | **166 (stalled)** | 14:43 | **yes — but not evaluating** |
| MDW | **0 all day** | 16:43 | **yes — but never evaluated** |

MIA freezing is correct (past window). LAX stalling at 166 and MDW never
producing a single decision, while BOTH are inside their own windows, is a
separate defect from the pricing blocker — and a direct violation of the
continuous-hunting requirement (HUNT-1): two of four stations are not hunting at
all. MDW is NOT explained by observations (298 rows stored, normal shape).
Cause not yet established; candidates are market listing / instrument
availability / subscription cap (the venue WS cap is 10 subs shared across
MARKET_DATA + TRADE).

### CONFIRMED: archive-table train/serve skew

**The frozen `p_hold` table is calibrated on a population the live strategy can
almost never reach.**

Generator identified: `scripts/analysis/generate_current_rung_hold_archive_table.py`
-> `build_archive_table` / `build_hold_cases`
(`scripts/analysis/mb_current_rung_edge_study.py:309-342,423`). The frozen header
pins corpus 2021-01-01..2025-12-31, complete 24h days only, dense stations only
(NYC excluded, L-13).

| | corpus (frozen `p_hold`) | live decision path |
|---|---|---|
| running max | POINT — `row.rounded_f`, one whole-°F int | INTERVAL — `RunningMax(lower_f, upper_f, exact_f)` |
| observation source | METAR archive, TENTHS (`precision_c_tenths=5`) | NWS 5-min feed, WHOLE °C (`=10`) |
| ambiguity gate | **none — `RunningMax.spans` never called** | `spans()` refuses 83-88% of decisions |
| population | ALL complete-day hours | only the unambiguous subsample |

`build_hold_cases` filters solely on `is_complete_day` (24/24 hourly coverage).
`RunningMax.spans` has zero references in `mb_current_rung_edge_study.py` or
`pmr_climatology_study.py`.

**Consequence:** `P_HOLD_LOWER` / `P_HOLD_UPPER` cannot be trusted as calibrated
probabilities for the decisions the live strategy actually takes. This undermines
the CRH family on its OWN terms, independently of the closed forecast-edge
finding — `p_hold` is a climatological persistence estimate, not a forecast, so
the 1.98x market-resolution result does not speak to it either way.

**Reframe — this argues FOR Option C, more strongly than "it unblocks the gate".**
The skew exists BECAUSE live runs on a coarse feed. The corpus assumed
tenths-precision observations. Feeding live tenths data at 5-minute cadence does
not merely open the gate; it RESTORES the conditions the table was calibrated
under. At zero lag it reproduces corpus semantics exactly — live
`exact_f = round_half_up_f(temp_c_tenths)` is precisely the corpus's
`rounded_f`. At the observed 16-40 min lag it gets partway (~53-66% exact), so
the match is partial and the surviving subsample is still non-random.

**Open and decisive:** is the skew merely a COVERAGE gap, or also a DIRECTIONAL
bias in `p_hold` itself? Measurable by re-running the corpus with the live
ambiguity gate applied and comparing per-cell `p_hold`. In flight. If the
gate-pass `p_hold` is systematically signed against the frozen value, the table
is invalid for live use and no feed fix rescues it.

## Gate-pass re-run: the skew is DIRECTIONAL (PROVISIONAL — under independent review)

**Reproduction control: UNVERIFIED — the claim did not survive audit.**
The measuring agent reported a 240/240 match of rebuilt Wilson-lower against
frozen `P_HOLD_LOWER`. An independent `python-reviewer` audit of the script found
that comparison is NEVER COMPUTED in `main()`: the script writes `full_rate =
cell.hold_rate` (the raw MLE `hold_count/n`), NOT `cell.p_hold_lower` (what
`P_HOLD_LOWER` stores, per `ArchiveCell.__post_init__`/`build_frozen_table`).
Those are different statistics and would essentially never match exactly. The
auditor judges that `cell.p_hold_lower` WOULD match deterministically if compared
correctly — `build_archive_table` runs the identical code path over the identical
corpus — but that is an expectation, not a measurement. Re-derivation requested;
do not cite 240/240 until it returns.

Gate-pass retention **21.2%** (23,019/108,420). All refusals are `spans()`
refusals; zero `no_value`. Gate-pass n >= 57 station-days per cell (n == station-days exactly, one case per
station-day per cell). **CORRECTED: the first agent called this "no cell
underpowered" against its own threshold of 30. The CORPUS'S OWN minimum is
`N_MIN = 90` (`mb_current_rung_edge_study.py:191`), so cells at n=57 ARE
underpowered by the study's own standard.**

Delta (gate-pass p_hold − full-corpus p_hold), 240 cells:

| stat | value |
|---|---|
| mean | **+0.1295** |
| median | +0.1288 |
| p10 / p90 | +0.0652 / +0.1861 |
| max abs | 0.2173 |
| n-weighted mean | +0.1253 |

- `|delta| > 0.02`: **98.8%** (237/240). `|delta| > 0.05`: **95.0%** (228/240).
- Sign: **237 positive, 3 negative, 0 zero** (most negative −0.0393).
- **Against the frozen Wilson LOWER — the value the strategy actually reads —
  mean +0.1692, min +0.0071, max +0.2577: EVERY cell positive.**

### The mechanism: the ambiguity gate is a near-oracle

The live gate passes only when `[lower_f, upper_f]` fits inside one rung, which
requires `lower_f == R` — the whole-°C feed CONFIRMING R from below. On the SFO
MAM h14 diagnostic, gate-pass days have `settled − R` exclusively in {0, +1}.

**CORRECTED — "near-oracle" was OVERSTATED.** Refused days are NOT uniformly
scattered: `settled − R = 0` is ALSO their single largest bucket (211/373,
56.6%). **The gate trims the TAILS** (negative-basis and > +1 cases) **without
relocating the centre.** The earlier framing — "selects days whose outcome is
already nearly determined" — claims more than the diagnostic supports.

**79 of 240 cells** still have gate-pass p_hold of exactly 1.0000; median 0.9259
vs full-corpus mean 0.7555.

### Consequence asymmetry — the NO side is the unsafe one (CORRECTED)

NO-side wiring verified: `decision.py:439-441` computes
`p_miss_lower = 1 − P_HOLD_UPPER.get(key)` and feeds it as `p_bound` into
`_finalize_take` (`:402-404`) against `break_even = price + fee(price)`. That IS
the estimand at risk.

**CORRECTION.** The first measurement compared gate-pass rate against
`P_HOLD_LOWER` — the WRONG bound for the NO-side question. No script had ever
compared it against `P_HOLD_UPPER`. Run directly by the domain reviewer:

- gate-pass rate exceeds frozen `P_HOLD_UPPER` in **233/240 cells (97%)**, NOT
  all 240.
- mean overshoot **+0.094**, NOT the +0.13..+0.17 first reported.
- **7/240 cells are NOT overstated** (dU <= 0, down to −0.085), concentrated at
  hours 12-13 interior cells — early window, weaker convergence to the final max.

- **YES side: conservative.** The table understates p_hold, refusing takes it
  could have made. Costly, not dangerous.
- **NO side: CONFIRMED UNSAFE** on 233/240 cells at ~+0.09 mean. NO-side hunting
  is a standing requirement, so this remains the live-risk finding — but at a
  smaller magnitude and with 7 exceptions.

### Why "recalibrate on the gate-pass subsample" is NOT the remedy

Gate-pass p_hold is near-degenerate (79 cells at exactly 1.0). A conditional
probability of ~1.0 means the GATE has already resolved the rung — that is a
modelling problem, not a table refit. Refitting would bake the oracle in.

### Stated uncertainties (carried, not resolved)

- The live feed was **MODELLED, not replayed**: METAR tenths → whole °C half-up,
  `precision_c_tenths=10`, `is_metar=False`, `received_at_ns == observed_at_ns`,
  with NO latency/staleness/publication-lag gate. Modelled retention 21.2% vs
  live's observed 12-17%; the extra live refusals are non-`spans` refusals whose
  directional effect was NOT measured and could in principle differ.
- Historical venue ladders do not exist, so `spans()` was evaluated against a
  SYNTHETIC ladder tiled at the study's own `proxy_rung` phase. Interior m=0 and
  m=1 bracket the two phases and both show the same sign, but MAGNITUDE is
  phase-sensitive.
- Not verified against live logs that the live refusal is the same `spans()` call
  at the same instant.
- Gate-pass Wilson CIs ignore WITHIN-STATION-DAY hour correlation (a station-day
  contributes up to 24 correlated hours), so quoted intervals are too narrow.
  Clustered restatement requested.
- The hour-boundary instant (`midnight + (hour+1)h − 1ns`) is a plausible
  end-of-hour convention but was NOT confirmed against `build_running_max_days`'s
  actual hour indexing.

### Status

**PROVISIONAL.** The measuring agent explicitly declined to self-approve.
`python-reviewer` audit RETURNED: all 15 claimed imports are GENUINE (no
reimplementation of interval arithmetic, °C→°F, `spans()`, or the Wilson
interval); the two new helpers (`coarse_c_tenths`, `ladder_for`) are correctly
disclosed as new; the synthetic ladder tiles contiguously with no off-by-one; no
silent exception handling, defaults or imputation — refusals fail closed
throughout. Verdict: TRUSTWORTHY WITH CAVEATS, the binding caveat being the
unverified reproduction control above. The coarse-feed model
(`precision_c_tenths=10`, `is_metar=False`) matches the repo's own documented
convention (`paper_replay.py` `_NWS_INTEGER_C_PRECISION_C_TENTHS`).

`prediction-market-reviewer` still in flight on the near-oracle mechanism and the
NO-side consequence. Do not act on this result until it returns AND the
reproduction control is re-derived.


## Domain review verdict (returned)

- **NO-SIDE SAFETY: CONFIRMED UNSAFE** — 233/240 cells, ~+0.09 mean against the
  correct bound `P_HOLD_UPPER`. Wiring verified at `decision.py:439-441`.
- **RESULT STANDS, WITH CAVEATS:** "every cell" is wrong (7/240 are not
  overstated); the 0.13-0.17 magnitude used the wrong bound; the retention-gap
  directional claim is unverified rather than false.
- **Recalibrating on the gate-pass subsample is INVALID** — 79/240 cells at
  literal p-hat = 1.0 with n below the corpus's own `N_MIN = 90` is conditioning
  on a COLLIDER, not a calibrated forecast.
- **The real remedy needs REAL historical venue ladders** (not synthetic,
  R-anchored ones) to decouple the gate from the outcome. **Those do not exist.**
  So the family is currently **UNSALVAGEABLE, not merely miscalibrated.**
- **Selection effect generalises:** any backtest edge for this family on
  gate-pass days is suspect for the same reason — consistent with this repo's own
  prior closures (`no-family-has-an-edge`, `forecast-edge-closed-pmus-rungs`).

Open, genuinely unresolved: the live-vs-modelled retention divergence (21.2%
modelled vs 12-17% live) was never measured for directional effect. Live refuses
on staleness BEFORE `spans()` runs (`decision.py:334-341`); the model has no such
gate. Plausibly shrinks n without moving the centre — but untested.

## RULING: Option C is REJECTED. No sub-degree high-cadence source exists.

### The premise was FALSE (coordinator error)

**There is no "MADIS 5-minute tenths stream."** Measured over the 2.26M-row
archive: **2,062,941 / 2,065,561 (99.87%) of 5-minute-grid rows carry a
WHOLE-DEGREE-C `T` group.** Genuine tenths appear only in the off-grid hourly
METAR at :53/:56 (174,881/196,937 = 88.8% non-zero).

The coordinator asserted tenths precision from a single sample row:
`KLAX 200150Z AUTO 26011KT 10SM 22/17 A2990 RMK T02200170 MADISHF`.
`T02200170` encodes tenths FORMAT, but the VALUE is 22.0 °C — a whole degree.
"Tenths T-group" was misread as "tenths precision". The originating Explore
agent had correctly reported `LIVE PATH PLAUSIBLE BUT UNPROVEN`; the coordinator
over-read that caveat into a fact and built a design track on it.

**Consequence:** the coarse NWS row is not DERIVED from a finer 5-minute
reading — the 5-minute reading IS the coarse row. There is nothing to intersect
it with at its own instant, which is also why the empty-intersection rate is
structurally 0: the NWS 5-min grid and the METAR :53/:56 instants NEVER coincide.

### Even granting the feed, the design fails

Real captured venue ladders, n = **71 station-days**, 3,479 instants:

| L (min) | exact | spans-refusal | coarse-wins |
|---|---|---|---|
| 0 | 0.106 | **0.558** | 0.894 |
| 15 | 0.094 | 0.571 | 0.906 |
| 30 | 0.086 | **0.582** | 0.914 |
| 60 | 0.071 | 0.602 | 0.929 |
| **NWS-only baseline** | 0.000 | **0.707** | 1.000 |

**Lag is not the binding constraint.** Refusal moves only 55.8% -> 60.2% across
L=0..60 against a 70.7% baseline. A tenths feed buys ~11-15 points AT ZERO LAG
and the majority of decision instants still refuse. **There is no L at which the
design survives.**

Block-bootstrap over station-days (2000 reps) at L=30: **0.582, 95% CI
[0.481, 0.678]**.

### This SUPERSEDES the earlier n=8 result

The earlier measurement reported 17.9% refusal at L=30 on 8 station-days and
flagged bimodality as a caveat. **The bimodality was not a small-sample
artefact — it worsens at full n:** 17.5% of station-days refuse at exactly 0.000,
**71.4% refuse above 0.40**, only 9.7% land in between. The 8-day sample drew the
easy tail. The powered re-measurement reversed the conclusion.

### Honest limits

- Only the n=71 arm is LADDER-MEASURED; the large-n arm (6,956 station-days) is
  LADDER-ASSUMED (2 °F tiling, anchor calibrated on the 76 real ladders) and runs
  ~8 points worse. Do not quote the assumed arm as measured.
- The real-ladder CI is wide (+/-10 points) and is the only ladder-measured evidence.
- 5,251 same-instant archive value conflicts (0.2%) resolved last-write-wins.
- The synthesis-validation 100% match is DEGENERATE: all 2,832 overlapping tenths
  values already ended in `.0`, so every candidate rounding rule agrees trivially.
  The relabel is validated; a rounding rule is not — and none is needed.

### Consolidated: every identified fix is now closed

| option | status | why |
|---|---|---|
| A — METAR-only R(t) | REJECTED | deletes the gate by construction; resolves onto demonstrably-wrong rungs at 19.1% |
| B — IEM `asos1min.py` | REJECTED | whole °F, no `metar` column; parser would drop every row |
| C — IEM MADIS 5-min | REJECTED | the stream is whole-°C, not tenths; and even at L=0 the majority still refuse |

This reaches the same wall already recorded in
`no-live-subdegree-observation-source` and `band-decider-stopped-at-stage0b`:
**the market prices integer-°C ambiguity, and no live sub-degree high-cadence
observation source has been found to exist.**

## Reproduction control: VERIFIED (re-derived 2026-09-20)

The earlier "240/240" claim was mis-attributed — it came from a second script
(`report.py`) that reconstructed `hold_count` as `round(full_rate * full_n)`,
re-called `wilson_interval` itself instead of using `ArchiveCell.p_hold_lower`,
and compared with a float tolerance. That was a REIMPLEMENTATION of the
quantization.

Re-derived correctly (`scratchpad/repro_check.py`), importing the generator's own
quantizer from `scripts/analysis/generate_current_rung_hold_archive_table.py:192`:

```python
def _quantize(value: float) -> Decimal:
    return Decimal(f"{value:.4f}")
```

Key re-mapping uses the generator's own `WIDTH_CODES` (:66-70). Comparison is
exact `Decimal == Decimal`.

```
cells rebuilt: 240   frozen keys: 240
EXACT Decimal match on P_HOLD_LOWER: 240/240   mismatches: 0
EXACT Decimal match on P_HOLD_UPPER: 240/240
cells with p_hold_lower None (n<N_MIN): 0
min cell n: 445
```

**Corpus identity established.** (Note: `min cell n: 445` is the FULL-corpus
table; the GATE-PASS subsample cells go as low as n=57, below the corpus's own
`N_MIN = 90` — the two figures are not in conflict.)

### Clustering resolved — and it STRENGTHENS the finding

A cell key is `(station, season, hour, width, m)`, so a station-day contributes
exactly ONE case per cell (verified `gp_n == gp_days` for all 240). Per-cell
Wilson intervals were therefore ALREADY station-day-clustered; the correlation is
ACROSS cells, not within. The 237/240 sign count must not be read as a 240-df
sign test.

Station-day cluster bootstrap (B=400, whole station-days resampled):

| quantity | value |
|---|---|
| mean-across-cells delta | **+0.1295** |
| clustered 95% CI | **[+0.1229, +0.1364]** |

Sign at progressively less-correlated aggregation:

| level | positive | min | max |
|---|---|---|---|
| (station, season, width, m) — 48 groups | 48/48 | +0.0443 | +0.1916 |
| (station, season) — 16 groups | 16/16 | +0.0987 | +0.1628 |
| **(station) — 4 independent groups** | **4/4** | +0.1197 | +0.1485 |

The sign is positive in every one of the 4 fully-independent station-level
groups and the clustered CI excludes zero by a wide margin. CI endpoints stable
to ~±0.001 at B=400; do not quote more digits.

### Hour-boundary: CONFIRMED against source

`RunningMaxDay.running_max_f` is documented as `R(t)` at the END of each
local-standard hour (`pmr_climatology_study.py:319`); the loop writes
`series[hour]` after folding each row (`:395`), back-fills empty hours (`:387`)
and the tail (`:398`); bucketing is `local_standard_hour` (`:245-255`). The
measurement instant `local_std_midnight + (hour+1)h − 1ns` is the last nanosecond
of hour h, admitting exactly rows with `local_standard_hour <= h`. Matches. Stays
inside the climate day at h=16 (zero `no_value` refusals in 108,420 cases).

### NO-side magnitude: the DOMAIN REVIEWER'S number stands

The measuring agent restated "roughly the same margin across all 240 cells".
**That is its ORIGINAL claim, computed against `P_HOLD_LOWER` — the wrong bound
for the NO-side question.** It never compared against `P_HOLD_UPPER`; the domain
reviewer confirmed no script in the scratchpad did, ran the comparison directly,
and measured **233/240 cells, mean +0.094**. The measured figure governs:

- **NO-side inflation: 233/240 cells (97%), mean +0.094.** NOT all 240, NOT +0.13-0.17.
- 7/240 cells are NOT overstated, at hours 12-13 interior.

### Status: the p_hold finding is now CONFIRMED, not provisional

Reproduction control verified, clustering resolved and strengthening, hour
semantics confirmed, script audited (genuine imports, no silent defaults, fails
closed). **TABLE INVALID FOR LIVE USE** stands: conservative on YES, unsafe on NO
across 233/240 cells. Remaining live-vs-modelled retention caveat (21.2% modelled
vs 12-17% live, staleness gate absent from the model) is unresolved but is not
plausibly sign-reversing.
