# H3 — Intraday running-max lock (hypothesis for critique, 2026-09-01)

Iteration 3. H1 and H2 (tail locks) fired 0/4. `cli_settlement_print_lock` was
REFUTED on real data: `docs/evidence/print_lock_refuted_2026-09-01.md`.

## The measurement that generates this hypothesis

From the 10.5h verified capture (671552 rows, 0 truncated), 122416
`OrderBookDepth10` records across two climate days:

| climate day | depth rows | rows carrying an ASK | winning rung rows | winning rung rows with ASK |
|---|---|---|---|---|
| 2026-08-31 (settled) | 21985 | 18653 (84.8%) | 3332 | **0** |
| 2026-09-01 (unsettled) | 100431 | 100424 (100.0%) | n/a yet | n/a yet |

The ladder is LIQUID on the offer side. What is missing is an offer on the one
rung that wins. And the NYC winner carried no ask at 03:30Z -- **3h before its
final printed, and ~10h after its climate day ended.**

**Therefore the market does not resolve on the CLI print. It resolves when the
day's maximum becomes PHYSICALLY DETERMINED** -- around and after the diurnal
peak. The print is paperwork. L-7 ("public information has no offer side")
is right but mis-timed: the information becomes public to the MARKET hours
before it becomes official.

## Hypothesis

A daily maximum is monotone non-decreasing. Let `R(t)` be the running observed
max at time `t` and `M` the final settled max, so `M >= R(t)` always.

As `t` passes the diurnal peak, `P(M > R(t))` collapses. There is therefore a
window -- after the peak, before the market has fully repriced -- in which the
bucket containing `R(t)` is very likely the settling bucket AND still carries an
executable ask below break-even. H3 says that window is non-empty and
harvestable long-only.

Entry: buy YES on the bucket containing `R(t)`, once `P(M > R(t))` is below a
pre-registered threshold, priced against the live ask.

## Why this is not a rerun of a dead strategy

- NOT `cli_settlement_print_lock`: triggers on an OBSERVATION, hours earlier,
  while offers still exist. Refuted only the post-determination window.
- NOT G-01's dead interior-bucket path: G-01 killed interiors AFTER THE
  PRELIMINARY PRINT, where preliminary->final REVISION breaks exact equality.
  H3 never uses a print. Its risk is physical (further temperature rise), not
  clerical, and it exits before any print exists.
- NOT `running_extreme_lock` (H1): that fires on OPEN TAILS, which the venue
  positions outside the day's actual -- 0/4. H3 targets INTERIOR buckets, which
  is where the venue's six-rung ladder puts the mode.

## GATE 0 — RESOLVED 2026-09-01 (was "the binding unknown")

**Does Breezy ingest intraday observations? Live: NO. On disk: YES, 5 years of them.**

*Live ingest — NO.* The NWS transport can construct exactly two URLs, both CLI
products, with the family hardcoded in the path string:
`/products/types/CLI/locations/{loc}` (`ingest/http.py:603`) and
`/products/{uuid}` (`:616`). `_fetch` is private (`:769`); there is no third URL
builder and no way to express one. No `/stations/{id}/observations`, no METAR,
no ASOS, no gridpoint call anywhere in `src/breezy/`.

*But R(t) is not absent — it is COARSE.* `RunningExtremeLockStrategy` already
treats a same-day non-final `NwsClimateDay` as a running high already printed
(`running_extreme_lock/strategy.py:177`, subscribe `:270`, consume `:304-305`).
So R(t) exists today at CLI-print granularity — roughly one PRELIMINARY per
site-day — not at hourly granularity. The open question was never existence; it
is whether ~1 sample/day is enough resolution to locate the post-peak window.
It is not: a single afternoon print cannot distinguish "before the peak" from
"after it."

*Archive — YES, and it is already on this machine.* Five years of IEM ASOS
observations, one file per station, at
`~/.local/share/breezy/archive/settlement-alignment-cache/`: raw METAR text,
`station,valid,metar`, `tz=Etc/UTC`, covering **2021-01-01 -> 2026-01-02** for
all five stations. **5-minute** cadence for LAX/MDW/SFO/MIA; **hourly** for NYC.
Instantaneous temperature comes from the METAR `T` remark group
(`scripts/analysis/settlement_alignment_study.py:99-101`, fetch at `:408-433`).

**Consequence — Gate 0 SPLITS, and only one half is blocked:**

| Premise | Data status | Blocked? |
|---|---|---|
| METEOROLOGICAL: `P(M > R(t))` by station x hour | ~5 yr x 5 stations of real 5-min obs, on disk | **NO — testable now** |
| ECONOMIC: is there an executable ask at trigger | 2 climate days of `OrderBookDepth10` | Needs the 09-01 tape + its finals |
| LIVE EXECUTION: R(t) at intraday cadence in-bot | no ingest path exists | **YES — needs a new Actor** |

**Look-ahead risk is NONE on the existing classes.** `ts_init` is real byte-receipt
time for every temperature-carrying class, backtests order by `ts_init`, and
`records.py:316-321` refuses any record with `ts_event > ts_init`. The trap
applies only to a NEW intraday class: its `ts_init` must be true receipt time,
never the measurement timestamp restamped after the fact.

**Minimal native-first live extension** (only if the meteorological premise
survives): a second Actor of the same shape as `NwsIngestActor`
(`ingest/nws_actor.py:429`) — native `Clock.set_timer` polling (`:636-670`),
existing cross-thread submit bridge (`:722-755`), existing `write_records`
(`persistence/catalog.py:422`), existing publish (`nws_actor.py:1444-1449`).
Four deltas: a `NwsStationObservation` `Data` subclass with `register_arrow`
(copy `nws_climate_day.py:383-389`); a `DataType` factory beside
`nws_actor.py:381` plus a `_data_type_for` branch (`:416-421`); one new URL
builder on `HttpTransport`; the Actor itself. The host allowlist already permits
`api.weather.gov` (`shared_state.py:99`) and needs no change.

**Blast radius of the transport change (codegraph, not inferred).** The two-URL
limit is a DELIBERATE invariant, stated at `ingest/http.py:562-566`: "The ORIGIN
is configurable so tests can retarget it; the PATHS are not... A caller supplies
what to fetch, never where on the origin to fetch it from." Both public methods
funnel into the private `_fetch` (`:769`), so a third endpoint cannot be reached
from outside and must be added INSIDE `HttpTransport`. Dependents:
`fetch_discovery_list` (`:656`) 48 callers in `nws_actor.py`; `fetch_product`
(`:713`) 15 callers; `HttpTransport` (`:522`) 10 callers in `shared_state.py`
and `probe_transport.py`. All three are covered by
**`tests/unit/test_probe_containment.py`** -- an existing containment contract
over what this transport may reach. A new URL builder must SATISFY that
contract, not merely be added beside it, and that test must not be weakened to
accommodate it. This raises the cost of the BL-24 delta above the four-step
estimate above.

**Nautilus has NO running-max primitive** — verified by full class inventory of
`indicators/` and `data/aggregation.pyx`. `DonchianChannel` is a fixed-count
rolling window over `Price` and will not take custom `Data`; `BarBuilder` keeps a
running high (`aggregation.pyx:150-154`) but is keyed on `Price` from
tick/bar types. The strategy must compute R(t) itself. L-1 null hypothesis:
REFUTED for the running max, CONFIRMED for the actor/timer/catalog plumbing.

**CORRECTION (2026-09-01).** An earlier revision of this file claimed the
strategy "computes R(t) itself, exactly as `running_extreme_lock/strategy.py:304`
already does." **That was FALSE and is retracted.** Verified against source:
`on_data` (`:304-319`) reads `data.tmax_f` straight off an `NwsClimateDay` CLI
product into `RunningExtremeObservation(tmax_f=data.tmax_f, ...)`, and
`decision.py:212` then does `running_f = observation.tmax_f`. There is no fold,
no accumulator and no `max()` over observations anywhere in
`src/breezy/strategy/`. The "running high" in that strategy is the running high
**NWS already computed and printed**. So the accumulator is absent from Breezy as
well as from Nautilus, and must be authored -- it is not an existing pattern to
copy. (Same pass: `_submit_delta:412` uses `order_factory.market(...)`, so that
strategy is a MARKET-order taker, unlike print-lock's bounded marketable limit.)

Do NOT propose that Claude, Grok or Codex backtest or simulate. Nautilus alone
runs backtests and execution.

## REVISION 2 (2026-09-01) — after Grok critique + independent tape measurement

### The hazard was named wrong in revision 1

`P(M > R(t))` is NOT the loss event. Interiors settle a CLOSED 2 F interval
`[A, A+1]`. The loss is `M > upper_f`, which equals `M > R(t)` only when `R(t)`
already sits on the rung's CEILING. If `R = 78` inside `[78, 79]`, a 1 F late
rise still pays in full.

**The conditioning variable is integer headroom `h = upper_f - R(t)` in {0, 1}.**
The strategy fires at `h = 0` -- the worst-conditioned cell -- so any pooled
number under-prices exactly where it would trade most. This is the same defect
prior feedback found in flat `min_p_hold`. `model_p` must be a TABLE over
`(headroom, hour, station[, month])` carrying the Wilson LOWER bound, never a
scalar `P(...) < epsilon`. Reusing the open-tail `MEASURED_MARGIN_MODEL_P` here
would import a DOWNWARD-risk table into an UPWARD-risk problem.

### Unit mismatch is load-bearing

Settlement is the CLI **integer** `tmax_f`. The METAR `T` group is tenths,
rounded `floor(F + 0.5)`, from a different instrument. So
`P(M_cli > R_metar) != P(M_cli > R_cli)`, and the METAR<->CLI basis (NYC is the
suspect, KNYC being a different thermometer) may be comparable to the 2 F rung
width. If it is, an ASOS-driven `R(t)` is unusable on an integer-settled ladder
and H3 dies on units alone, before any market question.

### What the tape now MEASURES (registry-derived, corrects revision 1)

Revision 1 said the 0-ask observation was "~10h after its climate day ended."
**That was wrong.** Against `sites.toml` `std_utc_offset_hours` and
`records.py:363-379`, capture starts 2026-09-01 00:41:05Z, which is INSIDE the
08-31 climate day and +1.68h (LAX/SFO) to +4.68h (NYC/MIA) AFTER a local-15:00
peak. 153857 deduped depth rows, 0 empty files, 9 truncated tails all belonging
to the live-appending instance and salvaged by prefix.

| station | winner rung | winner rows with an ask | adjacent rungs |
|---|---|---|---|
| MDW | `gte91lt92f` | **0 / 876** | ~100% offered @ 0.01 |
| MIA | `gte91lt92f` | **0 / 500** | ~100% offered @ 0.01 |
| NYC | `gte78lt79f` | **0 / 437** | ~100% offered @ 0.01 |
| SFO | `gte66lt67f` | **0 / 958** | ~100% offered @ 0.01-0.02 |
| LAX | `gte78lt79f` | **7 / 1075**, all @ **0.99**, gone in 90 s | ~100% offered @ 0.01 |

Winners identified from Breezy's own store (`custom_nws_climate_day`,
`is_final=True`, `is_superseded=False`), NOT from the catalog -- every
`instrument_close_*.feather` holds 0 rows.

**Status: UNTESTED AT ITS CORE, ADVERSE AT ITS MARGINS.** The ladder is liquid;
the winner specifically is not, from +1.7h post-peak onward. The sub-window H3
actually stakes its edge on -- peak to roughly +1.7h -- is unobserved for every
station-day on disk. The one ask ever seen on a winner was 0.99, which is
already negative-edge under the BL-19 cost model, so even the margin evidence
we have is economically dead.

### The counterparty question, which H3 must answer to survive

After the peak, everyone who could sell is gone: a market maker on a climate
prior reprices off the same public obs (the 08-31 book proves they already do
this WITHOUT waiting for a CLI print); retail buying the high they see are the
0.99 BIDS, not asks; an arb LIFTS leftover cheap YES, emptying the offer. The
only residual is a stale resting limit -- which is a cancel race, not a lock.
And a still-present ask IS the market saying `P(M > upper_f)` is not small, so
lifting it means taking the other side of a live meteorological disagreement.
Small `P` and a cheap ask may simply not coexist. Long-only cannot hedge the
next rung, so every 1 F that exits `[A, A+1]` is unhedgeable.

Breezy also polls CLI on a 300 s HTTP timer -- it is structurally SLOWER than
whoever empties the ask.

## Pre-registered kill criteria — REVISION 2

Ordered economic-gate-first, per the Gate 0 doctrine.

| # | Criterion | Kill condition |
|---|---|---|
| **0a** | **Data** | No intraday series in-bot -> UNIMPLEMENTABLE (currently TRUE; archive exists, live ingest does not). |
| **0b** | **Clock** | The hypothesized window is not on tape -> **UNTESTABLE, not DEAD**. Currently TRUE for peak -> +1.7h. |
| **0c** | **Units** | METAR<->CLI basis comparable to the 2 F rung width -> DEAD on units. |
| **1** | **Ask survival** | No executable ask on the `R(t)` rung inside the pre-registered window. BINDING. Requires P, clock and stratum pre-registered first, or it is unfalsifiable. |
| **2** | **Price** | Median **depth-aware VWAP** (not level 0) at or above `break_even(Wilson_lower(stratum))`. **The 0.99663 figure in revision 1 is WRONG** -- that is the OPEN-TAIL `p_hold` break-even. Interior stay is ~0.93 pooled and ~0.86 at MDW, putting real break-even in the **0.85-0.95** band. On a 0.01 tick only 0.99/0.98/... exist, so 0.99663 would wrongly admit 0.99. |
| **3a** | **Description** | If H3 is the routine post-peak lock it claims, it must fire on **>= 0.50** of in-window station-days. Below that the DESCRIPTION is false. (Revision 1's 0.20 was both the wrong number and the wrong kind of test: H1/H2's 0/4 was a POWER failure on 4 station-days, not an economic verdict.) |
| **3b** | **Economics** | Kept strictly separate from 3a. A rare-but-real edge must not be killed by a frequency floor. |
| **4** | **Monotonicity** | Revision 1 was CIRCULAR -- if the threshold IS the estimated P, it cannot fail in sample. Pre-register per-stratum caps on a FROZEN archive slice (G-01 rule: N >= 90/site, Wilson 95% UPPER vs cap), then measure on a LATER slice. |
| **5** | **Headroom-0 cell** | Must pass SEPARATELY. A pooled pass that fires at the ceiling is a fail. |
| **6** | **Station-stratified** | Must pass per station. Pooling is how MDW/NYC interiors survived until the powered study killed them. |
| **7** | **Information-set identity** | If time-from-physical-lock to empty-ask is indistinguishable from zero, DEAD regardless of how clean the T* distribution looks. This is L-7 at an earlier clock. |
| **8** | **Adverse selection** | If surviving asks concentrate on late-rise days, a fill means being in the cell the maker declined to cancel. |

## The decisive experiment — running NOW

Two clocks, never mixed.

**Physical premise** (no prices, no Nautilus): per-station-month CDF of T*, from
BOTH the ASOS series and the CLI `raw_text` TIME field (which Breezy's parser
currently discards). Pre-registered: `P(T* > 17:00 LST) > 0.05` at MDW/MIA/NYC
falsifies a clock rule there; bimodality at LAX/SFO falsifies a single-hour
threshold there. IN FLIGHT.

**Market gap** (the binding one): `OrderBookDepth10` on all six rungs across the
LOCAL AFTERNOON THROUGH EVENING of a live climate day -- roughly **19:00Z 09-01
-> 06:00Z 09-02** to span NYC/MDW through LAX/SFO, ideally to 13:00Z for the
finals. After the finals print, mark the winner and record ask present/absent
against (a) time of last new max, (b) first time after which no later
observation exceeds it -- the PHYSICAL lock, (c) the CLI print. Ask gone at (b)
or within one quote cycle -> the gap is zero and H3 is print-lock at an earlier
clock. Ask still present after (b) at a fee- and slippage-admissible VWAP -> the
gap exists, and the next question is whether those surviving asks are the
late-rise days.

**The 09-01 morning tape is NOT this experiment.** It covers 6.1-9.3h of
PRE-peak and zero post-peak. Morning asks on the eventual winner are pre-peak
mixing: reading them as "H3 lives" would be a false positive, and reading zero
morning asks as "H3 dead" would attribute the death to the wrong mechanism (a
book locked on the FORECAST, not on the observation). Capture must START before
the local peak and run continuously THROUGH it. The recorder is currently
positioned to produce exactly that, under a restart supervisor with a
2026-09-02 14:00Z deadline.

### Prerequisite that is easy to miss

The on-disk ASOS archive ends **2026-01-02**. It does NOT cover 2026-09-01, so
`R(t)` for today's tape cannot be reconstructed from what is already local. IEM
serves the current day (`settlement_alignment_study.py:405-433` is the sanctioned
fetch path), and IEM archives permanently, so this is retrievable tomorrow
alongside the finals rather than urgent today -- but the market-gap experiment
is unlabelable without it. Fetch 2026-09-01 ASOS for all five stations before
attempting to mark the winner against the physical lock.
