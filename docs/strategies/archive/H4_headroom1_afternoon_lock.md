> **ARCHIVED 2026-09-01 — DESIGN INPUT ONLY, economics measured.** No package
> exists under `src/breezy/strategy/`. Read the measured read first:
> `docs/evidence/h4_preliminary_economic_read_2026-09-01.md`.

# H4 — Headroom-1 afternoon lock (supersedes H3, 2026-09-01)

Iteration 4. H3 is REFUTED at headroom 0 and SURVIVES, narrowed, at headroom 1.
Evidence: `docs/evidence/pmr_climatology_2026-09-01.md` (2634 lines, ~1800
climate days x 5 stations, 2021-01-01 -> 2026-01-02).

## What killed H3 — and it was not the weather

At hour 23 the climate day is physically over, so on the OBSERVATION basis
`R(23) == M` by construction and late-rise crossings are exactly **0.000%** at
every station. Yet the settled CLI integer still lands outside the rung:

| station | headroom 0 crossing @23h | of which late-day physics | of which METAR<->CLI basis |
|---|---:|---:|---:|
| NYC | 54.824% | 0.000% | **54.824%** |
| MIA | 26.181% | 0.000% | **26.181%** |
| LAX | 24.297% | 0.000% | **24.297%** |
| SFO | 21.714% | 0.000% | **21.714%** |
| MDW | 14.994% | 0.000% | **14.994%** |

**The entire residual hazard at headroom 0 is instrument basis, not meteorology.**
Settlement is the NWS CLI integer; `R(t)` is only obtainable intraday from METAR,
a different thermometer read on a different cadence. Measured basis
(`CLI tmax_f - ASOS daily max`, whole F, n~1800/station):

| station | n | mean | median | P(=0) | P(abs>=1) | P(abs>=2) |
|---|---:|---:|---:|---:|---:|---:|
| NYC | 1736 | **+0.655** | **+1.0** | 44.009% | **55.991%** | **8.468%** |
| MIA | 1798 | +0.118 | +0.0 | 59.511% | 40.489% | 1.168% |
| LAX | 1812 | +0.103 | +0.0 | 56.126% | 43.874% | 2.704% |
| SFO | 1793 | +0.050 | +0.0 | 58.840% | 41.160% | 1.339% |
| MDW | 1825 | -0.053 | +0.0 | 64.329% | 35.671% | 0.658% |

At headroom 0 any `+1` basis is an automatic loss, and `+1` is the MEDIAN at NYC.
Kill criterion 0c (units) fires.

**The false positive this nearly produced.** On the `obs` basis, LAX headroom 0
reads as tradeable from 14h local standard. On settlement truth it is REFUTED --
no such hour exists at any station, in any season, at any threshold reaching 5%.
An analysis that used observations as though they were settlement would have
green-lit exactly the cell the strategy trades. This is the print-lock error in a
new costume: a measurement about a quantity the venue does not settle on.

## What survives — H4

At **headroom 1** a `+1` basis lands ON the ceiling and still pays, absorbing the
dominant error mode. Crossing bound on settlement truth, season-pooled:

| station | crossing @23h (h=1) | first hour the Wilson-95 UPPER bound stays <= 5% |
|---|---:|---|
| MDW | 0.409% | **16h** |
| MIA | 0.591% | **14h** |
| SFO | 0.654% | **15h** |
| LAX | 3.142% | **18h** |
| NYC | 7.953% | **never** |

**Entry.** Buy YES on the rung `[A, A+1]` when `R(t) == A` exactly -- i.e.
headroom `h = upper_f - R(t) == 1`, never `h == 0` -- at or after the station's
threshold hour in LOCAL STANDARD time, priced against the live ask.

**Universe.** MDW, MIA, SFO, LAX. **NYC is EXCLUDED** -- its instrument basis
alone (median +1) exceeds tolerance even at headroom 1, where it still crosses
7.95%.

**Seasonal carve-out.** Pre-registration PR-1 is falsified seasonally:
`P(T* > 17:00 LST)` exceeds 5% at MDW DJF (11.8% ASOS / 22.8% CLI) and NYC DJF
(12.1% / 20.0%), and on the CLI series also NYC MAM/SON and MDW MAM. A clock rule
is physically false there. **Exclude MDW in DJF.** NYC is already out. PR-2 is
NOT falsified: `T*` is unimodal at LAX and SFO in all four seasons, so no
marine-layer bimodality carve-out is needed.

**`model_p` is a table, never a scalar** -- over `(station, headroom, hour,
season)`, carrying the Wilson LOWER bound on the stay probability. It must not
import the open-tail `MEASURED_MARGIN_MODEL_P`, which is a DOWNWARD-risk table
for an UPWARD-risk problem.

## The trade-off this quantifies, and the economic gate

Stay probability rises through the afternoon while the book empties. Trigger at
the threshold hour and `model_p ~ 0.95`, so the ask must clear roughly 0.94 after
costs; wait until 23h and `model_p ~ 0.996`, but by then the winner is likely
unoffered -- the tape already shows 0 asks from ~+1.7h post-peak. That tension IS
the strategy, and it is now numeric rather than hoped-for.

Note this SUPERSEDES two earlier break-even figures, both wrong for this cell:
0.99663 (open-tail `p_hold`) and the 0.85-0.95 band estimated from G-01's
prelim->final interior stay. Both were differently conditioned. The break-even is
`break_even(Wilson_lower(station, headroom=1, hour, season))` against a
**depth-aware VWAP**, not level-0.

## STATUS — the economic gate is NOT yet measured

The meteorological premise now PASSES at four stations with pre-registered hours.
The binding question is unchanged and unanswered: **is there an executable ask on
the `h=1` rung at the trigger hour, below break-even, in size?**

That is measurable only on a tape covering the local afternoon through evening.
No such tape existed until today. Capture is running now under a restart
supervisor (deadline 2026-09-02 14:00Z) and is expected to yield the first
peak-window overlap in the programme.

**Do not build the strategy before that gate reports.** Ordering the economic test
last is the structural defect this programme has already paid for twice: every
brief that ran the settlement-side test first terminated at "gate PASS, economics
unknown", and print-lock reached a shipped implementation before anyone measured
whether the winning rung had an offer side. Gate 0 doctrine orders the economic
gate FIRST.

## Prerequisites before the gate can be read

1. Fetch 2026-09-01 ASOS for all five stations from IEM -- the local archive ends
   2026-01-02, so today's tape cannot be labelled with `R(t)` without it.
2. Mark the winner from the CLI finals printing 2026-09-02 05:00-13:00Z.
3. Label each depth row with `(R(t), headroom, hour LST, season)` and read ask
   presence and depth-aware VWAP at the pre-registered trigger, per station.
