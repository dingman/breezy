# Pre-registration — Decision-time clearance analogue (DTC study)

**Written:** 2026-08-27. **Revision 1.** **Status: PRE-REGISTRATION.**
**Written BEFORE any statistic in §§4-9 has been computed.** No decision-time
clearance figure, confusion matrix, leakage rate, residual-rise quantile or
proxy-conditioned agreement rate exists anywhere in this repository at the time
of writing. §3 records the data-availability inventory that *was* performed —
file existence, row counts and module absence only — and nothing in §3 is a
statistic about temperature, clearance or agreement.

**Authorises:** nothing. Computation is gated on the adversarial domain review
of §11. The work is proposed as backlog item **G-20**; registering it in
`docs/core/PROGRESS.md` is the coordinator's action, not this document's.

**Binding parents.** `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`
(revision 14, APPROVED) and `docs/evidence/settlement_bucket_guard_band_prereg_2026-08-26.md`.
Where this document reuses a rule from either — anchors, Branch A/B, power
floors, feasibility classification, NYC exclusion, retention-as-primary — it
**transcribes** the parent rule and cites it. It does not invent a parallel one,
and it may not relax one.

---

## 1. The question, and why the parent gate cannot answer it

The asymmetric settlement gate stratifies by **clearance**:

    K_true(c, d, θ)  =  | metar_unrounded_max_f(c, d)  −  θ_f |

where `metar_unrounded_max_f` is the climate day's **final** METAR-derived
maximum. That is a hindsight quantity. `asymmetric_gate_prereg_2026-08-26.md:442-446`
[R7] forbids substituting the final max for the decision-time conditioning
variable, in these terms:

> `build_threshold_cases` sets `threshold = metar_max.rounded_max_f - margin`
> — the city-day's **final** METAR max, a hindsight quantity — whereas §4
> conditions on the **intraday running max at Breezy's receipt time**. Same
> word, different conditioning variable. Substituting the final max would
> reintroduce exactly the look-ahead that DOM-2 exists to prevent.

`src/breezy/settlement/coverage.py:25-36` carries the same caveat about the
figures that motivate the coverage rule:

> That table is itself stratified by distance from the day's FINAL METAR max —
> a hindsight quantity the pre-registration forbids as a gating input at [R7].
> It motivates this module; it is NEVER an input to it.

**The consequence.** A verdict at any clearance stratum is a statement about a
population Breezy cannot identify while a contract is still tradeable. The gate
establishes that the METAR/CLI join behaves differently near the threshold than
far from it. It supplies no decision-time means of telling the two apart.

**So the question this study asks:**

> Does a decision-time-observable analogue of the clearance stratum exist, and
> how well does it map onto the pre-registered strata?

**And the outcome it must be able to return:** *no usable analogue exists* — in
which case the asymmetric formulation is unevaluable at decision time regardless
of what any tape shows, and that line of work ends. §9 states, numerically and
in advance, the evidence that produces that outcome.

## 2. Reframing — the brief's question, inverted, and why

The dispatching brief poses this as: *even a GO verdict at `[0,1)` would not
tell us how to trade, because at decision time we do not know which stratum a
contract is in.*

**That framing is correct in its logic but counterfactual in its premise, and
this document does not adopt it unchanged.** The programme has already recorded
the `[0,1)` result, in `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:881-890`:
against `BE(0.98, 0.06) = 0.981176`, the `[0,1)` cell is **STRUCTURALLY
UNREACHABLE** at LAX (Wilson-95% lower 0.7935), MDW (0.7800), MIA (0.8334) and
SFO (0.7917), while every `[1,2)`-and-above cell clears at 0.996+. A GO at
`[0,1)` is therefore not a live possibility for the four primary cities.

The live question is the **inverse**, and it is the one this study is designed
around:

> Can a decision-time rule **exclude** the boundary population tightly enough
> that the admitted set still clears break-even — and at a retention that leaves
> a strategy rather than a statistic?

That inversion does not weaken the brief's instrument; it is what the
instrument is for. The rate at which a truly-`[0,1)` contract is classified into
a wider stratum is exactly the rate at which a decision-time admission rule
**launders** the boundary population into the traded set. It is promoted here to
a primary falsification criterion (§9, F1) rather than a diagnostic.

**Stated plainly so it cannot be claimed later as a surprise:** the coverage
rule of `src/breezy/settlement/coverage.py` already voids those four cities
today. This study cannot un-void them by finding a proxy. The best available
outcome is a *different* pre-registered question — whether an explicitly
decision-time-defined admitted subpopulation clears its own break-even — and
answering it would require a new gate document, not an amendment to the parent.
**Nothing in this study authorises trading.** See §10.

## 3. Data-availability inventory — verified 2026-08-27, not assumed

Everything below is file existence, byte counts, line counts and module
absence. No archive value was parsed, aggregated or compared.

### 3.1 The historical METAR archive EXISTS — and it lives in `/tmp`

`/tmp/breezy-settlement-alignment-cache/` — 40 files, **299 MB**, all mtimes
2026-08-25 00:35–00:40Z. Content-addressed by URL SHA-256
(`settlement_alignment_study.py:338 cache_path_for_url`).

Five IEM ASOS CSV responses, `station,valid,metar` header, `tz=Etc/UTC`
(`settlement_alignment_study.py:390-415 asos_url`), each a whole-window fetch
with a ±1/+2 day UTC pad:

| City | cache file (SHA-256 stem) | lines incl. header |
|---|---|---:|
| MDW | `da7232fee15ab9f94cd47b59421173007c9e19f407129058f9fab21a5793833a.txt` | 571,150 |
| LAX | `d0f1851c5955f20f0a9a95b21ddc61fdcc77d2d494a3e438c3b594fb95407770.txt` | 569,405 |
| MIA | `c159b97d39f40e10ba6ff1db307d3b0b90ca634fc56431e2ca6af9d648183b53.txt` | 568,297 |
| SFO | `9f17318c9fabf1e48ca77d17a8b3ecb086985b164693718d00f3570bfd842263.txt` | 567,600 |
| NYC | `7d4cae947a4e0474ac036da7c24eb70973b389d2d77e51a2a021138364407b53.txt` | 55,810 |

These match the counts already published in
`settlement_alignment_diagnosis_2026-08-25.md:50-56` (raw METAR rows 571,149 /
569,404 / 568,296 / 567,599 / 55,809 — i.e. the line counts above less one
header row each), together with that table's T-group row counts and its mean
T-group rows per UTC day: **~303–307 for the four airport sites, 29.38 for
KNYC**. The remaining 35 cache entries (30 `.zip`, 5 small `.txt`) are the IEM
AFOS CLI product retrievals.

Each row carries an ordered UTC `valid` timestamp and the raw METAR text
containing the RMK `T`-group, which
`settlement_alignment_study.py:96-98 METAR_T_RE` already parses to tenths of a
degree Celsius. **The intraday running maximum up to an arbitrary time T is
therefore reconstructible for every city-day in the window.** This is the
study's load-bearing data finding and it holds.

**P0 defect, surfaced not designed around.** The archive exists only at an
ephemeral `/tmp` path, hardcoded as the default in three of the four analysis
scripts —
`scripts/analysis/settlement_alignment_diagnosis.py:39`,
`scripts/analysis/settlement_bucket_gate.py:42`,
`scripts/analysis/settlement_bucket_guard_band.py:45` — while the fourth,
`scripts/analysis/settlement_alignment_study.py:45`, points at
`scripts/analysis/cache/settlement_alignment`, **which does not exist** (the
directory is absent; `scripts/analysis/` contains only the five `.py` files, two
`pre_registration_*.md`, and `__pycache__`). One reboot or `tmpfiles` sweep
makes this study unrunnable *and* makes every published figure in
`settlement_alignment_diagnosis_2026-08-25.md`,
`settlement_bucket_gate_2026-08-25.md` and
`settlement_bucket_guard_band_2026-08-26.md` unreproducible.

**Pre-declared prerequisite P0:** before any G-20 computation, the archive is
relocated to a durable path under the operator's data root, SHA-256 manifested,
and the three `/tmp` defaults repointed. G-20 may not run against `/tmp`. If the
archive is already gone at the time of the run, G-20 halts and reports
**ARCHIVE-LOST**; it does not silently re-fetch, because a re-fetch is a
different (later-revised) IEM snapshot than the one the published figures came
from, and mixing them would make this study non-comparable to its parents.

### 3.2 There is NO historical NWS forecast archive — the brief's suspicion is CONFIRMED

The brief flagged this as believed-but-unverified. Verified:

- **No forecast module exists.** `find src/breezy -type d` yields
  `adapters/`, `adapters/polymarket_us/`, `domain/`, `features/`, `ingest/`,
  `normalize/`, `persistence/`, `registry/`, `runtime/`, `settlement/`. There is
  no forecast package. `src/breezy/features/` contains only `__init__.py`.
- **No forecast client exists.** `grep -rn "forecast" src/breezy --include=*.py`
  returns four hits, none of them code: `registry/sites.py` (a comment about the
  `open_meteo` sub-table), and prose comments at
  `adapters/polymarket_us/fees.py:150`, `symbology.py:165`, `parsing.py:70`.
  `grep -rn "aviationweather|mesonet|/stations/.*observations|ACIS"` across
  `src/breezy` returns **no fetcher** — the only ACIS/METAR references are gate
  *state* transitions (`ingest/gate.py:127-128, 356, 1213-1232, 1252`), i.e. an
  interface for receiving a cross-check verdict that nothing currently produces.
- **The registry carries coordinates, not forecasts.**
  `src/breezy/registry/sites.toml` has an `[sites.polymarket_us.<city>.open_meteo]`
  sub-table for all five cities, each carrying `settlement_eligible = false`
  (lines 139, 174, 215, 255, 297) plus `lat`/`lon`/`elevation_m`. The file's own
  header (lines 78-83) states these are "ENRICHMENT-ONLY coordinate data for
  forecast lookups ... namespaced so that no settlement code path can reach it".
  Coordinates are not a forecast archive.
- **The live catalog is three days deep.**
  `/home/jon/.local/share/breezy/catalog/polymarket_us/<CITY>/data/` holds only
  `custom_nws_climate_day/` and `custom_nws_raw_product/` — 15 files per city
  (21 for LAX), earliest `2026-08-24T19:50:55Z`, latest `2026-08-27T08:34:55Z`.
  Total `polymarket_us` catalog: **888 KB**. There is no observation stream and
  no forecast stream in it.

**Pre-declared consequence, binding.** A forecast-based decision-time estimator
— NWS gridpoint, NBM, Open-Meteo, or any other — **cannot be backtested at all**
in this repository. G-20 will not design one, will not stub one, and will not
report a hypothetical one as a candidate. If a future study wants one, it must
first accumulate a forecast archive of its own and pre-register separately. This
document says so rather than designing around data that does not exist.

### 3.3 There is NO live METAR ingestion — the proxy is backtestable but not yet producible

`src/breezy/ingest/` (`config`, `gaps`, `gate`, `http`, `nws_actor`,
`nws_envelope`, `product_index`, `records`, `routing`, `shared_state`) polls NWS
**CLI products**. Nothing polls observations. The consequence is stated here
rather than in the risk section because it changes what a GO would mean:

> A GO from this study would establish that a decision-time proxy is
> *computable from an idealised archive*. It would NOT establish that Breezy can
> produce that proxy live, because the component that would produce it does not
> exist. Any GO carries a mandatory build dependency (a METAR observation
> ingester with its own gap/staleness handling) and a mandatory backtest-vs-live
> parity check, neither of which G-20 delivers.

This asymmetry is also the first threat to validity (§12.1) and drives the
mandatory lag sensitivity of §6.4.

### 3.4 Fee coefficient — grounded, and the range is not a guess

The brief supplies `θ = 0.06`, verified across 729/729 captured observations,
`BE(0.98, 0.06) = 0.981176`. **Verified in repo:**
`TRADING_SYSTEM_ARCHITECTURE.md:95` ("Theta is now pinned at 0.06 (729/729
captured observations)"), `:457`, `:1612` (assumption A1), and the worked table
at `:464` giving `BE(0.98, 0.06) = 0.981176` and `BE(0.98, 0.09) = 0.981764`.

Two qualifications that the parent documents already record and that this study
inherits rather than discards:

1. A1 at `:1612` states the evidence is "all *captured*, none future". `θ` is
   pinned on observation, not guaranteed forward.
2. `roi_feasibility_2026-08-26.md:51-53` records the **Tier-1 evaluation bar as
   1.5x stressed fees — taker `0.09` rather than `0.06`**
   (`TRADING_ENABLEMENT_PLAN.md:487-490`), and `:86-88` labels 0.06 "unsafe
   until the fee schedule is live-resolved". `asymmetric_gate_prereg` §6 records
   the schedule as `[UNKNOWN]` with `assert_fee_schedule_known` fail-closed
   (G-15).

**Pre-declared θ range: `{0.06, 0.09}`.** The pessimistic end (0.09,
`BE = 0.981764`) governs every pass/fail. A result that clears at 0.06 but not
at 0.09 is recorded **THETA-CONTINGENT / CONDITIONAL on G-15**, never as a pass —
transcribing `asymmetric_gate_prereg` §6 and §7's feasibility table. `θ = 0.00`
is not used, at either end.

### 3.5 What is NOT in the archive, and must not be invented

- **Receipt timestamps.** The archive carries METAR *valid* times only. Any
  receipt-time modelling is a proxy and is treated as one (§6.4).
- **Historical Polymarket.us strike ladders.** The archive contains no record of
  which thresholds the venue actually listed on any historical day. This is a
  first-order design problem, not a footnote — see §5.3 and §12.2.
- **Trading hours (DOM-9).** Unresolved. §8 states how the study behaves without
  it rather than assuming a close time.

## 4. Pre-declared hypotheses

Stated before computation. Each is falsifiable by the criteria of §9.

- **H0 (null, and the default).** No function of decision-time observables
  recovers the pre-registered clearance strata well enough to support a
  decision-time admission rule. Specifically: either the residual rise after the
  decision time is too large for `M_obs(T)` to resolve 1 °F strata (H0a), or a
  proxy that does resolve them admits truly-`[0,1)` contracts at a rate that
  reintroduces the boundary error mass into the traded set (H0b).
- **H1.** A residual-adjusted decision-time proxy (P2, §6.3) classifies
  contracts into the parent strata with a truly-`[0,1)` leakage rate whose
  Wilson-95% **upper** bound is at or below 0.20, in a majority of in-scope
  cities at the primary decision time.
- **H2.** The settlement-agreement rate conditioned on the **proxy** stratum
  admission rule clears `BE(0.98, 0.09) = 0.981764` **and** the standing
  pre-registered settlement-alignment bar of **0.9906**
  (`settlement_alignment_study.py:47 PRIMARY_BREAK_EVEN`), at a Wilson-95% lower
  bound computed at the Holm-adjusted level, at a retained fraction of at least
  0.25.

**H0 is the default and the burden is on H1 and H2 jointly.** H1 without H2 is a
failure: a proxy that recovers the strata but whose conditioned agreement does
not clear break-even is not tradeable. H2 without H1 is also a failure, and a
more dangerous one: it would mean the admitted set clears on average while
silently containing boundary contracts, which is the coverage-rule bypass this
study exists to detect. Both must hold.

## 5. Definitions — every term pinned before computation

### 5.1 Climate day and timezone — the silent-off-by-one hazard

`src/breezy/registry/sites.toml:46-52` and `src/breezy/registry/sites.py:213-234`
separate two clocks, and the separation is load-bearing here:

- **Climate day**: fixed `std_utc_offset_hours`, **never DST**. `sites.py:216-226`
  explicitly discards `iana_tz` from `ClimateDayWindow` to prevent exactly the
  substitution that would make the climate day DST-following.
- **Venue settlement clock**: `settlement_time_local` / `settlement_timezone`
  (08:00 America/New_York, DST-following), plus the conditional 11:00 ET
  METAR-review delay.

**Pre-declared, binding for G-20:**

1. An observation with UTC valid time `t` belongs to climate day `d` for city
   `c` iff `t + std_utc_offset_hours(c) ∈ [d 00:00, d+1 00:00)`. Day assignment
   uses **valid time**, consistently, everywhere — transcribing
   `asymmetric_gate_prereg` §7 point 2b, which requires this be stated rather
   than left implicit.
2. **Decision times `T` are expressed in local STANDARD time** on the climate
   day and converted to UTC by the same fixed `std_utc_offset_hours`. They are
   never DST-following and never venue-ET. A DST-following `T` would shift by an
   hour across roughly two-thirds of the archive window and would silently
   change which observations count as "so far" — differently in summer than in
   winter, i.e. differently in exactly the season where the daily-max window
   matters most.
3. The reconstructed `M_obs` and the parent studies' `M_final` must be derived
   through the **same** climate-day helper. A separate reimplementation is
   forbidden; a divergence between the two would appear as apparent proxy error.
   G-20 must assert this by constructing `M_final` as `M_obs(c, d, T = end of
   climate day)` from its own code path and checking it against the parent
   study's daily maxima for every city-day, halting on any mismatch.

### 5.2 The observed maximum at T

    M_obs(c, d, T) = max over T-group air temperatures of the observations
                     assigned to climate day d for city c whose valid time
                     is <= T

Units: °F, unrounded, converted from the T-group's tenths-of-°C by the parent
study's existing conversion. If no qualifying observation exists, `M_obs` is
**undefined**; the `(c, d, T)` cell is excluded and the exclusion is counted and
reported by reason. It is never backfilled, never carried forward from the
previous day, and never defaulted to a climatological value.

    M_final(c, d) = M_obs(c, d, end of climate day d)

### 5.3 Thresholds — the ladder must not be drawn around the answer

`build_threshold_cases` in `settlement_alignment_study.py` synthesises
`threshold = metar_max.rounded_max_f − margin` for `margin ∈ (0,1,2,3)`. That
construction draws the threshold **around the day's outcome**. Reusing it here
would evaluate the proxy only on thresholds that are, by construction, within
3 °F of the final max — a population no venue listed, and one selected using the
very quantity the proxy is forbidden to see.

**Pre-declared: G-20 constructs a decision-time ladder.** For city `c` and
calendar month `m`, the threshold set is the integer °F ladder

    Θ(c, m) = { round(μ̂(c, m)) + j : j ∈ {−6, −5, ..., +5, +6} }

where `μ̂(c, m)` is the mean daily maximum for city `c` in calendar month `m`,
estimated **leave-one-year-out**: for a city-day in year `y`, `μ̂` is fit on the
archive's other years only. The ladder is thus a function of `(c, m, y)` and of
strictly-prior-and-later *other-year* climatology — never of day `d`'s own
observations, and never of `M_final(c, d)`. A ±6 °F span at 1 °F granularity is
chosen to bracket the region where a daily-max contract is plausibly listed
while keeping every stratum from `[0,1)` to `[5,∞)` populated; it is declared
now and may not be widened or narrowed after seeing a cell count.

**Leave-one-year-out is not perfect purity** and this document does not claim it
is: it uses years the live bot would not have had. It removes the *day-level*
lookahead, which is the leak that matters for stratum assignment, and it leaves
a *climatology-level* one, which biases toward a ladder better-centred than a
live bot's would be. Direction of that residual bias: **favourable to the
proxy**, therefore a pass is weakened by it and a failure is not explained by
it. Stated here so it cannot be presented later as a control that ran.

The hindsight-anchored `rounded_max_f − margin` ladder may be computed as a
**secondary sensitivity only**, labelled as such, and may not carry any verdict.

### 5.4 Clearance — true and proxied

    K_true(c, d, θ)  =  | M_final(c, d)  −  θ_f |          [hindsight]
    sign_true        =  sign( M_final(c, d) − θ_f )        [recorded, secondary]

Strata, transcribed from `asymmetric_gate_prereg` §4:
`[0,1)`, `[1,2)`, `[2,3)`, `[3,5)`, `[5,∞)` °F.

The absolute-value form is the brief's and `coverage.py`'s stratum variable. The
parent gate's §4 uses the **signed** `running_max − s`. G-20 records the sign as
a secondary field on every case so the two can be reconciled, and states in its
output which form each reported table uses. It may not mix them within a table.

    K_hat(c, d, θ, T)  =  the decision-time proxy, §6

## 6. The proxy — and how [R7] purity is made structural rather than careful

### 6.1 The purity requirement

Every input to the estimator must be observable at `T`. Any input requiring the
day's final max, the CLI product, or any observation with valid time `> T` is
disqualifying. The brief requires this be **structurally checkable rather than a
matter of care**. Pre-declared mechanism:

1. G-20 defines a frozen dataclass carrying **exactly** the decision-time
   information set:

       DecisionSnapshot(city, climate_day, decision_time_utc,
                        observations_le_T,        # tuple, valid time <= T
                        threshold_f, calendar_month,
                        residual_table_version)

   `M_final`, CLI `tmax_f`, `K_true`, and any observation later than `T` are
   **structurally absent** from it.
2. The proxy function's signature accepts **only** a `DecisionSnapshot`. It
   takes no other argument and reads no module-level state beyond the versioned
   residual table of §6.3.
3. **Mandatory test A (truncation invariance):** building a snapshot from a
   day's full observation list and from the list truncated at `T` must yield
   **identical** objects.
4. **Mandatory test B (post-`T` negative control):** re-run the entire proxy
   pipeline on a corpus where every observation with valid time `> T` is
   replaced by adversarial garbage (NaN-free but wildly out of range). Every
   proxy stratum assignment must be **bit-identical** to the clean run. A single
   difference is a leak and halts the study.
5. `K_true`, the CLI label, and `M_final` are joined **only** in the scoring
   step, downstream of every proxy call, in a module that the proxy module does
   not import. G-20 must add this as an `import-linter` contract, alongside the
   existing layering contract (G-07), so the direction is enforced by the build
   rather than by review.

A study output lacking evidence of tests A and B is incomplete and may not carry
a verdict.

### 6.2 P1 — the naive proxy (zero free parameters)

    K_hat_1(c, d, θ, T) = | M_obs(c, d, T) − θ_f |

Reported because it is the honest strawman and its failure mode is predictable a
priori: `M_final ≥ M_obs(T)` always, so P1 systematically **understates**
clearance for contracts the day has not yet resolved, and its error is exactly
the residual-rise distribution of §7.1. P1 carries no verdict. It exists so that
any improvement claimed for P2 is measured against something, rather than
asserted.

### 6.3 P2 — the residual-adjusted proxy (primary)

    K_hat_2(c, d, θ, T) = | ( M_obs(c, d, T) + R̂(c, T, m, y) ) − θ_f |

`R̂(c, T, m, y)` is the **90th percentile** of the residual rise
`D = M_final − M_obs(T)` for city `c`, decision time `T`, calendar month `m`,
estimated **leave-one-year-out**: for a city-day in year `y`, `R̂` is fit on the
archive's other years only, and the fitted table is versioned and frozen before
any evaluation-side statistic is read.

Input-by-input availability at `T`:

| Input | Available at T? | Justification |
|---|---|---|
| `M_obs(c,d,T)` | yes | observations with valid time ≤ T; §5.2 |
| `θ_f` | yes | contract term; ladder from other-year climatology, §5.3 |
| `c` | yes | registry constant, `sites.toml` |
| `T` | yes | the clock |
| `m` (calendar month) | yes | the calendar |
| `R̂` | yes | fit on strictly other years, frozen and versioned before evaluation |

**Why the 90th percentile and not the mean or median.** The operational error is
one-directional: the danger is admitting a contract whose final max will rise
past the threshold after the decision, i.e. under-estimating the eventual max.
A high quantile shifts `K_hat` in the direction that treats near-threshold
contracts as near-threshold, which is the conservative direction for an
admission rule. The 90th percentile is a declared judgement, not a tuned value:
it is the conventional "most-but-not-tail" quantile, it is fixed before any
residual figure is read, and **it may not be swept.** Sweeping it across
{p50, p75, p90, p95, p99} and reporting the best would manufacture a false
positive across five cities and three decision times; that is precisely the
selection surface this document exists to close. If a future study wants the
quantile as a free parameter, it needs its own pre-registration.

### 6.4 The lag sensitivity — load-bearing here, unlike in the parent

`asymmetric_gate_prereg` §7 [R8] withdrew a conservatism claim for a 45-minute
receipt lag, on the correct ground that a constant additive shift cannot change
the **relative order** of observations, so an order-determined statistic is
invariant to it.

**That reasoning does not transfer to this study, and the difference must not be
elided.** `M_obs(c, d, T)` is defined by a **real clock cutoff at `T`**, not by
an ordering. Shifting every observation's effective availability by `LAG`
removes from the information set exactly those observations with valid time in
`(T − LAG, T]`. At ~305 observations per day for the airport sites, a 45-minute
lag removes roughly the last nine or ten reports before the decision — the most
informative ones. `LAG` is therefore genuinely load-bearing and its effect is
one-directional (it can only reduce information).

**Pre-declared:** the primary run uses `LAG = 0` (`valid ≤ T`). A **mandatory**
sensitivity run uses `LAG = 45 min` (`valid ≤ T − 45 min`), the pessimistic end
of the 5–45 minute window the parent records. Both are reported for every
primary cell. A result that holds at `LAG = 0` but not at `LAG = 45 min` is
recorded as **LAG-CONTINGENT** and may not be reported as a pass, because the
live receipt latency is unmeasured (no METAR ingester exists — §3.3) and
assuming the favourable end of an unmeasured range is how the parent document
earned its seventh BLOCK.

## 7. The three measurements

### 7.1 Q1 — how much of the day's final max is already determined by T

Purely descriptive; carries no verdict. For every `(c, T, m)` and pooled over
`m`, report the distribution of

    D(c, d, T) = M_final(c, d) − M_obs(c, d, T)      (>= 0 by construction)

with: `n`, `P(D = 0)`, mean, and the p50 / p75 / p90 / p95 / p99 / max
quantiles, in °F. Also report `n_undefined` — city-days with no observation at
or before `T` — by city and `T`.

This panel is the **irreducible uncertainty any decision-time estimator
inherits**, and it is the input to falsification criterion F4 (§9). It is
reported first, and it is reported in full for all three `T`, so that a reader
can see the information curve rather than a single chosen point.

### 7.2 Q2 — does the proxy recover the strata?

For every `(c, T, proxy ∈ {P1, P2}, LAG ∈ {0, 45})`: the full **5×5 confusion
matrix** of proxy stratum against true stratum, with raw counts, plus row and
column marginals.

**Overall accuracy is explicitly NOT the headline** and may not be reported as
one — it is dominated by the wide strata, which are easy and which nothing
depends on.

**Headline statistic:**

    LEAK(c, T) = P( K_hat ∉ [0,1)  |  K_true ∈ [0,1) )

reported with a **Wilson 95% UPPER bound**. Upper, because the operational need
is to bound the leakage from above; a lower bound on an error rate answers no
question anyone is asking. Compute it as
`1 − wilson_lower_bound(non_leak_count, n)`, exactly the construction already in
`scripts/analysis/preliminary_final_revision_rate_study.py:271`. **Reuse it. Do
not re-derive a Wilson interval.** (`wilson_lower_bound` itself:
`scripts/analysis/settlement_alignment_study.py:206`.)

Report alongside, for context and never as the headline: the reverse error
`P( K_hat ∈ [0,1) | K_true ∉ [0,1) )`, which costs opportunity rather than
money, and per-stratum recall.

### 7.3 Q3 — does the conditioned agreement rate clear break-even?

Define the **decision-time admission rule**, using proxy P2:

    ADMIT(c, d, θ, T)   iff   K_hat_2(c, d, θ, T) >= 1.0 °F

i.e. the decision-time analogue of "not in the boundary stratum". Then, per
`(c, T, LAG)`:

- `A_admit(c, T)` — settlement agreement over admitted city-day-threshold cases.
  The agreement predicate is **the parent's, unchanged**: the same CLI-`tmax_f`
  versus rounded-METAR-max comparison the existing scripts implement. G-20
  reuses that code path; it does not define a new notion of agreement, because a
  new one would make this study incomparable to the gate it is about.
  Reported as a Wilson **lower** bound at the Holm-adjusted level (§8).
- `RET(c, T)` — retained fraction of eligible cases, **and** retained city-day
  fraction. Retention is a **PRIMARY result, not a diagnostic**, transcribing
  `settlement_bucket_guard_band_prereg_2026-08-26.md:77-96`.
- `CONTAM(c, T) = P( K_true ∈ [0,1) | ADMIT )`, Wilson 95% **upper** bound. This
  is the direct measurement of the coverage rule being bypassed at decision
  time: the fraction of what the bot would trade that is, in truth, boundary
  population.
- Miss-direction split among admitted failures: METAR above CLI versus below,
  per `settlement_bucket_guard_band_prereg` §Retention Cost. The above-CLI
  direction is the one that costs money, and MDW is flagged a priori (§8.4).

Also report `A(c, k̂, T)` for **every** proxy stratum `k̂`, not only the admitted
set, so that the whole surface is visible and no cell can be quietly omitted.

## 8. Design decisions, pre-declared with reasoning

### 8.1 Decision times T — three, chosen from structure, not scanned

Trading happens intraday against a daily-max threshold, so `T` trades
information against remaining opportunity. Scanning many `T` and reporting the
best is how a false positive is manufactured. Pre-declared set, in **local
standard time** (§5.1):

| `T` (LST) | Role | A priori justification |
|---|---|---|
| 10:00 | secondary | Early. Most opportunity, least information. Establishes the low end of the information curve. |
| **13:00** | **PRIMARY** | The last hour that is unambiguously **before** DOM-9's stated 14:00–16:00 daily-max window. The decision time at which an estimator faces the study's central difficulty in full. |
| 16:00 | secondary | The close of DOM-9's window. Most information, least remaining opportunity; the high end of the curve. |

The three points come from an **exogenous structural fact** — DOM-9's recorded
14:00–16:00 local daily-max window, transcribed in `asymmetric_gate_prereg` §4 —
and not from any observed performance. **Forbidden, explicitly:** adding a
fourth `T` after seeing results; reporting a "best `T`"; moving the primary.

**Only 13:00 LST carries a verdict.** If 13:00 fails while 16:00 passes, that is
reported as *"clears only at a decision time whose tradeability is
unestablished, DOM-9 being unresolved"* — never as a pass. This asymmetry is
declared now precisely because 16:00 is the point most likely to flatter the
estimator (much of the max already realised) and least likely to be tradeable.

### 8.2 Multiple comparisons — declared family, and the correction

The full grid is 5 cities × 3 `T` × 5 strata × 2 proxies × 2 LAG values. Most of
it is descriptive. Pre-declared split:

- **PRIMARY FAMILY — carries the verdict.** Proxy P2, `T = 13:00 LST`,
  `LAG = 0`, the four in-scope cities (NYC excluded, §8.3), two tests each:
  `LEAK(c, 13:00)` against F1 and `A_admit(c, 13:00)` against F2.
  → **8 primary tests.**
- **SECONDARY / DESCRIPTIVE — everything else.** Reported in full, in the same
  document, so nothing can be cherry-picked. May not carry a verdict, may not be
  substituted for a primary cell, and may not rescue a failed one.

**Correction: Holm–Bonferroni at family-wise α = 0.05 over the 8 primary
tests.** Chosen over plain Bonferroni because it is uniformly more powerful at
the same family-wise error rate and assumes no independence — and these tests are
correlated, sharing an archive and a proxy. Chosen over an FDR procedure because
a single false GO here would authorise live capital, so family-wise control is
the correct error concept: we want the probability of *any* false pass bounded,
not the expected proportion.

**Applied at the interval, not to a p-value.** Where a Wilson bound is the
operative statistic, Holm's step-down is implemented by evaluating the Wilson
bound at the **adjusted one-sided level** `α_i` for that test's rank, rather than
by adjusting a p-value after the fact. This keeps the reported interval and the
decision rule the same object.

### 8.3 Per-cell power floors, and the exclusions

Transcribed from `asymmetric_gate_prereg` §7 rather than re-invented:

- **`N(c, k̂, T)` is computed and recorded BEFORE any observed rate is read.**
  For the agreement statistic, the anchor `p̂_anchor(c, k̂)` is the parent's:
  Branch A (archive cell ≥ 200 cases) uses the archive-derived stratified
  Wilson-95%-lower conditional agreement rate; Branch B (below 200) uses `2c−1`
  for `[0,1)`/`[1,2)` and `c` otherwise, per the parent's table. **Which branch
  fired, the sample count, the anchor value and the feasibility classification
  must be recorded for every cell** — a study output missing any of the four is
  incomplete and may not be used for a verdict.
- For `LEAK`, the floor is a **precision** floor rather than a power floor:
  the smallest `N` for which the Wilson 95% upper half-width at the pre-declared
  `LEAK_max = 0.20` is at most `LEAK_max / 2 = 0.10`. Below that, the leakage
  estimate cannot distinguish "well under the bar" from "at the bar".
- Cells below their floor are **UNDERPOWERED**, contribute to no verdict, and
  are **never pooled upward** to manufacture power.
- **Mandatory feasibility classification before computation**, using the
  parent's three-way table (FEASIBLE / THETA-CONTINGENT / STRUCTURALLY
  UNREACHABLE) evaluated across `θ ∈ {0.06, 0.09}`.
  **Pre-declared prediction:** the `[0,1)` *agreement* cell is expected to come
  back STRUCTURALLY UNREACHABLE at LAX, MDW, MIA and SFO under **any** proxy,
  because a proxy stratum containing truly-`[0,1)` days inherits their error
  mass, and `TRADING_SYSTEM_ARCHITECTURE.md:881-890` already records those cells
  at 0.7800–0.8334 against a break-even of 0.981176. This prediction is recorded
  now so that its confirmation cannot be presented as a finding, and so that the
  study's real question is visibly the §7.3 admitted-set one.

**UNDERPOWERED here resolves immediately; it does not sit.** Transcribing
`asymmetric_gate_prereg` §7 [R13]–[R14]: the archive is **fixed** and does not
grow with tape capture, so a cell underpowered today is underpowered
permanently. There is no clock to run out. A primary cell that is UNDERPOWERED
at first classification converts **immediately** to a stated, evidence-labelled
NO-GO for that city — *"the decision-time population cannot be estimated from
available archive data, therefore the falsification test cannot be run"* — and
that NO-GO **counts** toward the two-city programme rejection of §9. No
extension may be granted by amending this document.

**NYC is EXCLUDED from the primary verdict**, on the parent's ground and only
that ground: `asymmetric_gate_prereg` §7's pre-declared exclusion, KNYC's ~29
T-group observations per day against ~305 at the ASOS sites
(`settlement_alignment_diagnosis_2026-08-25.md:50-56`). That deficit is
**more** disqualifying here than in the parent, not less: this study's entire
construction is an intraday running maximum, and at ~29 observations/day the
running max at 13:00 LST is built from a handful of reports. NYC is reported
separately, clearly labelled secondary, and its result may not be pooled with
the four. **This exclusion is declared now and may not be reversed after seeing
a result.**

**MDW is NOT excluded** and is flagged for mandatory separate scrutiny on
directional-sign grounds, transcribing the parent §5 and §7: MDW's mean signed
error is `+0.0527 °F` with 56.37% of non-zero days running METAR > CLI — the
direction that costs money. MDW stays in the primary family **precisely so that
it can fail it.** Removing MDW after seeing a failure is forbidden by this
document, and MDW's number must appear in any headline.

### 8.4 DOM-9 (trading hours) — how the study behaves without it

DOM-9 is unresolved: the venue's intraday trading close is unknown. This study
**does not assume one**, and does not truncate anything by market hours. The
quantities it measures — residual rise, stratum confusion, METAR/CLI agreement —
are properties of the observation-and-settlement relationship, not of the
market, exactly as the parent's [R9] establishes for its power anchor.

The consequence is confined and stated: G-20's results describe what a decision
at `T` could have known, not whether a trade at `T` was possible. **A GO from
this study is therefore conditional on DOM-9** and must be labelled
CONDITIONAL-DOM-9 in every headline. If DOM-9 later resolves to a close before
13:00 LST for a city, that city's primary result becomes inapplicable and must
be re-run at a `T` before the true close under a new pre-registration — not
re-labelled under this one.

## 9. Falsification — numeric, and stated before computation

Evaluated at the **primary** cell only: proxy P2, `T = 13:00 LST`, `LAG = 0`,
θ at the pessimistic end `0.09`, Wilson bounds at the Holm-adjusted level, over
the four in-scope cities.

**Each criterion below fires per city.** Any single criterion firing in **two or
more** of the four in-scope cities falsifies the decision-time analogue.

- **F1 — Leakage.** The Wilson 95% **upper** bound on `LEAK(c, 13:00)` exceeds
  **0.20**.
  *Rationale, a priori:* the coverage rule exists because the `[0,1)` population
  is untradeable. If more than one in five truly-boundary contracts is
  classified into a wider stratum, the proxy does not implement that rule — it
  launders it. 0.20 is set **deliberately generous**, so that failing it is
  unambiguous rather than marginal; clearing it is necessary and not sufficient,
  since F2 still governs.

- **F2 — The admitted set does not clear break-even.** The Wilson 95% lower
  bound on `A_admit(c, 13:00)` fails to exceed **either**
  `BE(0.98, 0.09) = 0.981764` **or** the standing pre-registered
  settlement-alignment bar of **0.9906**. Both must be cleared; the binding one
  is 0.9906.
  *Rationale:* 0.9906 is `settlement_alignment_study.py:47 PRIMARY_BREAK_EVEN`,
  the bar every prior settlement gate in this programme was judged against.
  Introducing a laxer bar for a study whose whole subject is a decision-time
  weakening of that gate would be the rescue pattern the parent §1 warns about.
  A result clearing 0.981764 but not 0.9906 is a **FAIL** and is reported as
  one; a result clearing at θ = 0.06 but not θ = 0.09 is THETA-CONTINGENT and is
  **not** a pass.

- **F3 — Retention collapse.** `RET(c, 13:00) < 0.25` of eligible cases, or the
  retained **city-day** fraction `< 0.25`.
  *Rationale:* `settlement_bucket_guard_band_2026-08-26.md` recorded a
  post-hoc rescue whose retention collapsed to **12.97%**, and the parent
  prereg's §Falsification names the REQ-SETTLE-03a/R6a mode where
  `BOUNDARY_UNRESOLVED` silently consumes the addressable market. 0.25 is
  roughly double that recorded failure. **It is a declared judgement, not a
  derived constant**, fixed here before any retention number is seen.

- **F4 — No information at the decision time.** The 90th percentile of
  `D = M_final − M_obs(13:00)` is at or above **3.0 °F**.
  *Rationale:* the strata are 1 °F wide at the boundary. If the typical
  unrealised rise spans three stratum widths, then no function of `M_obs(13:00)`
  can distinguish `[0,1)` from `[3,5)`, and the failure is **informational**
  rather than a defect of any particular proxy — a better estimator would not
  help. 3.0 °F is three stratum widths, chosen from the stratum definition, not
  from any observed distribution.

### 9.1 The programme-terminating outcome — pre-declared and reachable

**If F1 or F4 fires in two or more in-scope cities at the primary cell, the
study returns `NO USABLE ANALOGUE EXISTS`.**

That verdict means: the asymmetric clearance formulation is **unevaluable at
decision time regardless of any hindsight-stratified statistic any tape could
produce**, and the asymmetric-gate line of work ends. It is reported
**immediately and prominently**, and it does **not** route to more tape,
because F1 and F4 are properties of the **fixed** IEM archive. More tape cannot
change `D`, and waiting on a clock that has nothing left to tell us would be the
unmotivated delay the parent's [R14] removed.

This is the outcome the brief requires the study to be able to return, and §7.1
computes F4's input before any proxy is even constructed — so the terminating
finding is reachable at the study's first table, not conditional on the rest of
the design working.

### 9.2 What a pass does and does not authorise

If none of F1–F4 fires in two or more cities, the result is **NOT** a GO to
trade. It authorises **exactly one** thing: re-opening the asymmetric gate's
`H(c, k̂)` computation with a **decision-time** stratum variable, under a **new**
pre-registration with its own adversarial review. Trading remains gated on, at
minimum:

- **G-15** — fee schedule unresolved; `assert_fee_schedule_known` fail-closed.
- **G-16** — ≥14 days of joined tape not yet started.
- **DOM-9** — trading hours unknown (§8.4).
- **A live METAR observation ingester, which does not exist** (§3.3), plus its
  own backtest-vs-live parity evidence.
- **G-02's standing verdict: ROI is NO-GO** (`roi_feasibility_2026-08-26.md`;
  `TRADING_SYSTEM_ARCHITECTURE.md:93-98`). This study measures observability, not
  profitability, and cannot rescue that verdict.
- **The coverage rule of `src/breezy/settlement/coverage.py`**, which voids the
  four primary cities on their current hindsight `[0,1)` classification and is
  not amended by anything here.

**A pass is a licence to ask a better question, not to place an order.**

## 10. Scope and prohibitions

- **No trading logic, no order submission, no egress of any kind.** G-20 is an
  offline archive study. Barrier N2 fails the build if an execution-egress
  module appears; nothing in this design introduces one.
- **Cache-only.** No Polymarket calls, no credentials, no prices, no orders. No
  network fetch at all: G-20 reads the relocated archive (§3.1 P0) and halts
  with **ARCHIVE-LOST** rather than re-fetching.
- **Reuse, do not re-derive:** `wilson_lower_bound`
  (`settlement_alignment_study.py:206`); the Wilson-upper construction
  (`preliminary_final_revision_rate_study.py:271`); the CLI parsing, T-group
  regex, climate-day helper and agreement predicate already in the parent
  scripts. A re-derivation is a divergence risk with no upside.
- **No sweeping of the residual quantile, the admission cut-off (1.0 °F), the
  decision-time set, the ladder span, or any falsification constant.** Each is
  pinned in §§5, 6, 8, 9 with an a priori rationale. A later study may sweep any
  of them under its own pre-registration.
- **Every claim in the G-20 output must be one the computation supports.** This
  is the codebase's named recurring defect — `asymmetric_gate_prereg` §10k
  records it as its own: *"prose promises a property the mechanism doesn't
  deliver"*, found in eight of thirteen review rounds. §6.1's tests A and B,
  §8.3's four-fields-per-cell requirement, and §5.3's explicit statement of the
  leave-one-year-out residual bias are this document's structural answers to it.
  They are mechanisms, not intentions.

## 11. Required adversarial domain review

G-20 is **not authorised for computation** until an independent reviewer,
briefed to attack rather than approve, answers all of the following. **A bare
APPROVE with no findings is treated as a failed review, not a passed one.**

1. **Is the P2 proxy [R7]-pure in fact, or only in prose?** Attack §6.1's
   snapshot construction and tests A/B. Name any path by which post-`T`
   information could reach a stratum assignment — including through the
   leave-one-year-out residual table, the §5.3 ladder, or the climate-day helper
   shared with `M_final`.
2. **Is the §5.3 threshold ladder a genuine fix or a relabelling?** Build the
   strongest case that leave-one-year-out climatology still leaks, and state the
   direction of the residual bias. If it flatters the proxy, does §5.3's stated
   direction correctly follow?
3. **Are the F1–F4 constants (0.20, 0.9906/0.981764, 0.25, 3.0 °F) genuinely
   capable of firing, or drawn so the study cannot fail?** Apply the DOM-1 test
   that killed the original gate: *is the measured quantity bounded away from
   failure by construction?* Apply it in **both** directions — is any criterion
   bounded away from *passing* by construction, which would make the study a
   foregone NO-GO rather than a test?
4. **Is `T = 13:00 LST` defensible as primary, or is it chosen to fail?** The
   document argues 16:00 flatters and 10:00 is needlessly pessimistic. Attack
   that. If 13:00 is systematically before the daily max at every city, is the
   primary cell measuring an estimator or measuring the climatology of afternoon
   heating?
5. **Does §2's inversion of the brief's question preserve what the brief was
   after, or quietly substitute an easier question?** The brief asked whether a
   decision-time analogue *recovers* the strata; this document additionally asks
   whether an admission rule *excludes* the boundary. Is that a strengthening or
   a softening?
6. **Is the Holm family of 8 the right family?** Argue that `CONTAM`, `RET`, or
   the secondary `T` should be inside it, or that 8 is already inflated by the
   correlation between `LEAK` and `A_admit` within a city.
7. **Does the absence of a live METAR ingester (§3.3) make the whole study
   premature?** Build the case that G-20 should be blocked behind that build,
   and the case that measuring the archive ceiling first is the cheaper
   ordering.

## 12. Threats to this study's validity — the top three, in my own design

### 12.1 Archive-vs-live divergence in the observation stream — the largest

IEM's ASOS archive is a **curated, post-hoc** product. Corrections are folded
in, late-arriving reports appear in valid-time order, and there is no receipt
timestamp at all (§3.5). `M_obs(T)` reconstructed as `valid ≤ T` therefore models
a poller that never missed a report, never saw a downward COR after acting, and
had zero latency — and, per §3.3, **no such poller exists in Breezy today**, so
its real behaviour is unmeasured rather than merely idealised.

**Consequence, and it is not small:** every number this study produces is an
**upper bound on live proxy quality**, and the G-20 output must label it as such
in every table caption, not once in a footnote. The `LAG = 45 min` sensitivity
of §6.4 bounds one component of the gap (latency). It bounds neither the
missed-report component nor the intraday-COR component — and the intraday COR is
the one mode `asymmetric_gate_prereg` §8.2 singles out as *not* conservative for
an asymmetric rule, because it can retract a clearance after a position is open.
Neither is measurable from this archive. They are named here as unbounded
residual risk, not modelled.

### 12.2 The stratum variable is threshold-indexed, and no historical ladder exists

Both `K_true` and `K_hat` depend on `θ_f`, and the archive records no strike the
venue actually listed (§3.5). The parent scripts sidestep this by synthesising
thresholds from the final max — the exact hindsight construction this study
exists to avoid (§5.3). §5.3's leave-one-year-out climatological ladder removes
the day-level leak, which is the one that would corrupt stratum assignment.

**What it does not remove:** the ladder is still not the venue's. If
Polymarket.us lists strikes concentrated where *its own* forecast puts the day's
max, the real listed population is systematically closer to the boundary than a
climatology-centred ladder — which would make `LEAK` measured here an
**under-estimate** of live leakage. That is the dangerous direction, it is not
correctable from this archive, and G-20 must state it as a limitation on any
pass. The only real fix is a captured historical ladder, which is G-16/G-18
territory and not available to this study.

### 12.3 The boundary cell is the smallest cell, and pooling would hide it

Conditioning simultaneously on city, decision time, proxy stratum, calendar
month and LAG shrinks cells fast. The `[0,1)` cell is both the smallest and the
one whose contamination decides everything — so the failure mode is that the
study reports a clean-looking admitted-set number while the cell that governs it
was never powered.

The design's answer is threefold and each part must be verifiable in the output:
compute every `N(c, k̂, T)` **before** reading any rate; mark sub-floor cells
UNDERPOWERED and **never pool upward**; and — following `asymmetric_gate_prereg`
[R13]/[R14] — resolve UNDERPOWERED **immediately** to a stated NO-GO rather than
letting it sit, since the archive is fixed and no clock will change it (§8.3).
The residual risk this leaves: the per-month conditioning in the §6.3 residual
table is the thinnest stratification in the design. If monthly cells prove too
thin, the pre-declared fallback is **seasonal** (DJF/MAM/JJA/SON) rather than
pooled-annual, and that fallback fires **on the cell count**, before any rate is
read — never after seeing a residual figure.

## 13. Review status

- **Revision 1** — adversarially reviewed per §11 on 2026-08-27. Verdict:
  **BLOCK** — 6 CRITICAL, 9 HIGH, with a ten-item minimum set required before
  computation. Recorded in full at
  `docs/evidence/DTC_PREREG_REVIEW_2026-08-27.md`.
- **Revision 2** — this document. §15 discharges all ten blocking items as
  pre-declared amendments `[D1]`-`[D10]`. **AWAITING RE-REVIEW**, scoped per the
  reviewer's instruction to those ten items and not the whole document.

Computation (G-20b) is **NOT AUTHORISED**. It is gated on: revision 2
re-reviewed and approved; prerequisite **P0** (§3.1, extended by `[D6]`) --
archive relocated off `/tmp`, SHA-256 manifested, cache-only accessor in place
with no HTTP client constructible on the G-20 path; prerequisite **P1**
(`[D5]`) -- per-stratum anchors re-derived on this study's own §5.4 stratum
definition; and the §6.1 purity tests A and B (B as rescoped by `[D8]`)
passing.

## 14. GREEN criterion for backlog item G-20a (this document)

This document written, adversarially reviewed per §11, and the verdict recorded
verbatim with its findings — in the same §10-style record the parent
pre-registration uses.

**Computing the statistics of §7 is explicitly NOT part of G-20a.** It is G-20b,
and it requires: this document approved, P0 discharged, and the §6.1 purity
tests A and B passing. Computing anything from §7 before then would defeat this
document's entire purpose.

## 15. Revision 2 — amendments required by adversarial review

Revision 1 was reviewed adversarially per §11 on 2026-08-27 and returned
**BLOCK**: six CRITICAL and nine HIGH findings, with a ten-item minimum set
required before computation. The verdict is recorded in full in
`docs/evidence/DTC_PREREG_REVIEW_2026-08-27.md`.

The findings cluster around a single mechanism, and naming it is the point of
this revision. §5.3 replaced the parent's ladder `θ = rounded_metar_max − margin`
with an independent climatological ladder — correctly, because the parent's
ladder *is* the hindsight the study exists to remove. But four rules were
transcribed from the parent as constants and predicates without their
generating mechanisms, and those mechanisms depended on the old ladder. The
transcriptions are therefore invalid in their new setting. This is the
inherited-reasoning defect the document was written to avoid, reproduced inside
the document itself, and it is exactly the §10k failure mode: **prose promising
a property the mechanism does not deliver.**

Each amendment below is pre-declared **before any statistic is computed** and
supersedes the cited text. Amendments carry `[D#]` markers, following the
parent's `[R#]` convention.

---

**[D1] The agreement predicate is redefined as two-sided settle-equality.**
Supersedes §7.3's "the agreement predicate is **the parent's, unchanged**",
which is **withdrawn**.

`settlement_alignment_study.py:313-315` computes:

    for margin in (0, 1, 2, 3):
        threshold = metar_max.rounded_max_f - margin
        hit = label.tmax_f >= threshold

`hit` is one-sided — *did CLI clear the strike?* It coincides with settlement
agreement **only** because `θ = rounded_metar_max − margin` makes
`rounded_metar_max ≥ θ` true by construction for every `margin ≥ 0`. §5.3
destroys that identity. Reused as §7.3 instructed, `A_admit` would measure
`P(CLI tmax ≥ θ)` — approximately the fraction of a centred ladder lying below
the day's max, near 0.5 — and F2 would fire at every city, returning a **false
NO-GO carrying §9.1's terminating language** on a statistic that never measured
the join.

Pre-declared: agreement is

    AGREE(c, d, θ)  ≡  1[cli_tmax_f ≥ θ]  ==  1[rounded_metar_max_f ≥ θ]

The parent's `hit` field is **not reusable** outside the parent's hindsight
ladder. §10's "reuse, do not re-derive" instruction is amended: reuse the
parsing, joining, and caching paths; **do not** reuse the scoring predicate.

**[D2] `K_hat_2` is redefined as a directionally correct plausible range.**
Supersedes §6.3's point estimate and its stated rationale.

Revision 1 defined `K_hat_2 = |(M_obs(T) + R̂) − θ|` with `R̂ ≥ 0` the p90 of `D`,
claiming a high quantile "shifts `K_hat` in the direction that treats
near-threshold contracts as near-threshold". That holds only where
`θ > M_obs + R̂`. For `θ < M_obs` the absolute value **reverses** it: adding `R̂`
moves the estimate *away* from the strike. A day with true clearance
`M_final − θ = 0.4` and `M̂ − M_final = 2.0` yields `K_hat_2 = 2.4` → stratum
`[2,3)` → **ADMITTED**. Because `R̂` is the p90, `M̂ > M_final` on ~90% of days,
so this is systematic laundering of the entire `sign_true > 0` half of the
boundary population, not tail behaviour — and raising the quantile makes it
worse, the exact opposite of the stated rationale. §5.4 records `sign_true` but
revision 1 defined no rule that consumes it.

Pre-declared:

    K_hat_2(c, d, θ, T)  =  min over M ∈ [M_obs(T), M_obs(T) + R̂]  of  |M − θ|

which is monotonically conservative on both sides of the strike and reduces to
the intended behaviour above it. Declared now, before any LEAK figure is seen;
it may not be revisited after one is.

**[D3] Every interval is computed on the city-day, not the case.**
Applies to §7.2, §7.3, §8.3, §9. Revision 1 was silent on clustering.

All strikes from one city-day share one `M_final`, one `M_obs(T)`, one `R̂`, and
one CLI label. The unit of independent randomness is the **city-day**. The
parent inherited this at 4 margins/day; §5.3 raises it to 13 and revision 1
never revisited it, inflating effective sample size ~13× and narrowing every
interval ~3.6×.

The direction of harm is the permissive one, on the criterion the study exists
to protect: F2's Wilson **lower** bound is pushed *up*, making break-even easier
to clear. It also understates F1's upper bound on leakage and corrupts §8.3's
precision floor.

Pre-declared: every reported interval uses a **city-day cluster bootstrap**
(10,000 resamples, resampling unit = city-day, percentile method, seed recorded
in the output). Declared now, not chosen after interval widths are seen.

**[D4] F3's denominator is redefined; F2 binds on the nearest admitted stratum.**
Supersedes §9 F3 and the F2 target in §9.

*F3 as written cannot fire.* With 13 integer strikes per city-day and an
admission rule excluding only strikes within 1.0 °F of a real-valued estimate,
at most 2 of 13 are ever excluded: `RET ≈ 11/13 ≈ 0.846` arithmetically, for
every city, every `T`, every `LAG`, every `R̂`. The retained city-day fraction is
identically 1.0, since no city-day loses all 13 strikes. The 0.25 constant was
transcribed from a 12.97% collapse that arose from **whole-city-day exclusion**
— a different mechanism. This is the document's own DOM-1 test failing on its
own criterion: bounded away from failure before any data is read.

Pre-declared: retention is measured against a **decision-relevant denominator**
— strikes within a plausible tradeable band of the estimate,
`|θ − M_obs(T)| ≤ 3.0 °F`. The 3.0 °F band is declared here, before any
retention number is seen, and is the same three-stratum span F4 uses. The
"retained city-day fraction" clause is **struck**: under any ladder it is
identically 1 and measures nothing.

*F2 as written is diluted to near-unfailable.* Once [D1] is applied,
settle-equality fails only when `θ` lies strictly between `cli_tmax_f` and
`rounded_metar_max_f`. Under the parent's ladder every case sat within 3 °F of
the max, densely inside the disagreement-sensitive region; under a ±6 °F
climatological ladder the admitted set is dominated by strikes 3–7 °F away that
agree trivially. `A_admit` would sit near 0.999 almost regardless of
contamination. The one criterion meant to catch the laundering [D2] identified
is the one the ladder change disarms.

Pre-declared: **F2 binds on `A(c, k̂ = [1,2), 13:00)`** — the nearest admitted
proxy stratum, which §7.3 already computes — against the same two bars
(`0.9906` and `BE(0.98, 0.09) = 0.981764`, both required). The pooled
`A_admit` figure remains a **reported secondary**, never the falsification
target.

**[D5] The transcribed anchors are misaligned by 0.5 °F. Re-derivation is
prerequisite P1.**
Affects §2 (lines 71-75), §5.4, §8.3.

`bucket_for_margin` (`settlement_alignment_study.py:200-207`) takes the
**margin** as its sole argument. It labels the margin, not a measured
clearance. With `θ = rounded_max_f − margin`:

| parent bucket label | actual true clearance `|unrounded − θ|` |
|---|---|
| `0-1F` | `[0, 0.5]` |
| `1-2F` | `[0.5, 1.5]` |
| `2-3F` | `[1.5, 2.5]` |

`TRADING_SYSTEM_ARCHITECTURE.md:881-890` is honest about this and writes
"≤0.5 °F (→ `[0,1)`)". Revision 1 dropped the qualifier and presented
0.7800–0.8334 as rates for the `[0,1)` stratum **as §5.4 defines it** (true
clearance, unrounded). They are rates for the harder inner half `[0, 0.5]`. The
wider `[0,1)` rate is necessarily **higher**.

Two consequences, both load-bearing. (a) §2's premise — that a GO at `[0,1)` is
not a live possibility, which is the entire justification for inverting the
brief's question — rests on a stratum that **has never been measured**. (b)
§8.3's per-stratum anchor `p̂_anchor(c,k̂)` is misaligned by 0.5 °F for every
stratum, propagating into feasibility classification and into `N`.

Pre-declared, as **prerequisite P1**, discharged before G-20b: re-derive the
per-city, per-stratum agreement rates from the archive on **DTC's own §5.4
stratum definition** (true clearance `|unrounded_metar_max_f − θ|`, unrounded,
against the [D1] two-sided predicate, with [D3] intervals). Until P1 is
discharged, every anchor carried from the parent is labelled
**`MARGIN-BUCKET-DERIVED, ±0.5 °F MISALIGNED`** wherever it appears, and §2's
premise is labelled **UNVERIFIED ON THIS STUDY'S STRATA**.

P1 is a derivation on the fixed archive, not a test of any hypothesis in §4. Its
outputs are inputs to §8.3's power computation and may **not** be used to select,
tune, or re-tune any falsification constant in §9.

**[D6] The archive is cache-only and manifest-verified. Egress is made
structurally impossible.**
Supersedes §3.1's P0 and §10's "cache-only" claim, both of which are policy, not
mechanism.

`settlement_alignment_study.py:343-353` contradicts the claim outright:

    def fetch_text_cached(client, cache_dir, url, delay_s):
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_path_for_url(cache_dir, url)
        if path.exists():
            return path.read_text(...)
        response = client.get(url, timeout=60.0)   # silent re-fetch

The helper creates the missing directory and fetches on any cache miss.
Repointing a default only changes *where* the miss happens. A single missing or
renamed file would silently mix a 2026-08-27 IEM snapshot into a 2026-08-25
study — precisely the non-comparability §3.1 warns against — and breach §10's
no-egress scope. Revision 1's P0 also left `settlement_alignment_study.py:45`
aimed at a non-existent directory, which is the **one module that owns the
fetch helpers**.

Pre-declared, discharged before G-20b:

1. A **cache-only accessor** that raises `ARCHIVE-LOST` on miss — no `mkdir`, no
   `client.get`, no HTTP client constructed at all on the G-20 path. Structural,
   in the manner of §6.1's purity requirement, not policy.
2. **Full manifest re-verification at the start of every G-20 run**: all 40
   digests, file count, and total byte count. Any mismatch halts with
   `ARCHIVE-CORRUPT`, a **distinct** condition from `ARCHIVE-LOST`. Silent
   corruption or a partial copy is the realistic failure; total absence is not.
3. The manifest records the **URL → digest** mapping, not filenames alone
   (`cache_path_for_url` keys on `sha256(url)`), so a relocated cache is provably
   the same *responses* and not merely the same bytes.
4. The manifest-of-manifests digest, archive path, file count, and byte count
   are recorded in the G-20 output, anchoring every published figure to a
   specific archive state.

§3.1's prose describes a `/tmp` location that no longer holds the archive; it is
superseded by the durable path and manifest digest recorded under P0.

**[D7] The terminating verdict is restricted to F4 and restated in
observation-only terms; F4 is pinned.**
Supersedes §9.1 and §9's F4 rationale.

§9.1 asserted that F1 or F4 firing means the formulation is unevaluable
"**regardless of any hindsight-stratified statistic any tape could produce**".
F4 — an informational property of `D` — can support a statement about
*observation-based* estimators **at T = 13:00 LST**. F1 cannot support anything
beyond *P2 as specified, at 13:00, at LAG 0* — a single estimator whose
specification revision 1 got wrong ([D2]). And §3.2 established that the
forecast-based estimator class **cannot be tested here at all**, so no result in
this study licenses a claim over "any decision-time analogue". This is §10k
appearing in the very section that declares the programme-terminating outcome.

Pre-declared:

- **F4 firing at ≥2 cities** returns `NO USABLE OBSERVATION-ONLY ANALOGUE AT
  T = 13:00 LST`. It does **not** speak to forecast-based estimators, which
  §3.2 places outside this archive's reach.
- **F1 firing at ≥2 cities** returns `P2 DOES NOT IMPLEMENT THE COVERAGE RULE` —
  a NO-GO for P2, not for the analogue class.
- Neither routes to more tape; both are properties of the fixed archive.

F4's statistic is also repaired. Revision 1 paired a **p90** with a
**central-tendency** rationale ("if the *typical* unrealised rise spans three
stratum widths"). A p90 of 3.0 °F is entirely compatible with a p50 of 0.5 °F
and excellent discrimination on 80% of days — and post-13:00 LST summer rise at
MDW/SFO very likely exceeds 3 °F at p90, so as written F4 would probably fire at
≥2 cities and terminate the programme on an inference its statistic does not
carry. Revision 1 also left the pooling basis unstated while §7.1 reports `D`
both per-`(c,T,m)` and pooled, which differ by several °F — a live selection
surface on the criterion that terminates the programme.

Pre-declared: **F4 fires iff `p50(D) ≥ 1.0 °F` AND `p90(D) ≥ 3.0 °F`**, pooled
over months, per `(c, T = 13:00 LST)`, with quantiles by the **nearest-rank**
estimator. The paired form earns the "informational, not proxy-specific"
reading; the single tail statistic did not.

**[D8] `R̂` is labelled an idealisation, purity test B is rescoped, and `R̂` is
refit per LAG.**
Supersedes §6.3's availability table, §6.1 point 4, and §6.4.

*Availability.* §6.3 marks `R̂` "available at T — yes, fit on strictly other
years". Leave-one-year-out includes **future** years: a live bot at T in 2022
cannot have fit a residual table on 2023–2025. §5.3 states this honestly for the
ladder; §6.3 wrote an unqualified "yes" for the identical construction. The
brief's void condition is any input not genuinely observable at T.

Pre-declared: `R̂` and the ladder are refit on an **expanding prior-years-only**
window, dropping the earliest archive year. The archive spans 2021–2025, so this
costs one year and removes the objection outright. Where any figure is
nonetheless produced under LOYO for comparison, it is captioned
**`IDEALISED — other-year fit, not live-available`**, as §12.1 already captions
the archive.

*Purity test B is unpassable as written.* §6.1 point 4 requires replacing
**every** observation with valid time `> T` corpus-wide with adversarial garbage
and asserting bit-identical proxy strata. But `R̂` is fit on `D = M_final −
M_obs(T)`, and `M_final` requires post-T observations — so garbling them
corpus-wide destroys the `R̂` and `μ̂` fits and the run *must* differ. The test
halts the study by construction, and would therefore be silently rescoped at
implementation time, which is how a purity test becomes theatre.

Pre-declared: test B garbles post-T observations **in the evaluation city-year
only**, holding the frozen, versioned `R̂` table and ladder constant (both are
already declared frozen before evaluation). A **second negative control**
garbles other-year data and asserts the frozen table digest is **unchanged**.

*LAG.* §6.4 makes the LAG = 45 min run mandatory but never says whether `R̂` is
refit at `T − 45` or reused. Reusing it mis-specifies the estimator and
confounds information loss with mis-specification.
Pre-declared: `R̂` is refit per `(c, T, m, y, LAG)`, with its own frozen table
version and digest.

**[D9] The determination is PER-CITY, with the 2-of-4 rule layered above it.**
Supersedes §9's and §9.2's programme-only rule. **More permissive than the
parent, and restored here.**

`asymmetric_gate_prereg_2026-08-26.md:843-860` declares, under `[R3]`: "**The
trading determination is PER-CITY.** Each in-scope city receives its own GO /
NO-GO", with the two-city programme trigger layered *on top*. That granularity
was added specifically because a prohibition on dropping MDW is, without it,
"theatre" — "discipline that changes no action". Revision 1 kept only the
programme rule, so a city with a LEAK upper bound of 0.45 alongside three clean
cities would produce **no adverse verdict at all**, and §8.4's MDW paragraph —
transcribed almost verbatim from the parent — became precisely the theatre
`[R3]` abolished.

Pre-declared, transcribing the parent in full:

1. Each in-scope city receives its **own** verdict on each of F1–F4.
2. The 2-of-4 rule is the **programme-rejection layer above** that, not the
   whole rule.
3. MDW's result appears in the headline determination whatever it is; a
   three-city pass may never be reported without MDW's number alongside it
   (parent `[R3]` point 4, carried forward).

**[D10] The ladder's bias direction is not derived and is replaced by a
per-statistic table; F2/F3 are made terminating; the seasonal floor is pinned.**

*Direction.* §5.3 claims the residual climatology-level lookahead is
"**favourable to the proxy**, therefore a pass is weakened by it and a failure is
not explained by it". This is asserted, not derived, and is probably inverted: a
better-centred ladder places *more* strikes near the day's max, **enlarging the
boundary population and making classification harder**. The sentence is
load-bearing — it is the reason a failure would be read as real rather than as
ladder artifact.

Pre-declared, replacing the single-direction claim:

| statistic | effect of leave-one-year-out ladder centring | direction |
|---|---|---|
| `LEAK` (conditioned on true boundary membership) | ambiguous | **unknown** |
| boundary cell count `n` | more strikes near the max | increased (more power) |
| `RET` | more strikes near the max | decreased |

§12.2's separate and opposite-signed claim — that venue-listed strikes sit
nearer the venue's own forecast, making measured `LEAK` an **under-estimate** —
is **retained unchanged**. It is correctly reasoned, correctly identified as the
dangerous direction, and correctly declared uncorrectable.

*F2/F3 failure had no declared programme consequence.* §9's preamble says any
criterion at ≥2 cities falsifies, but §9.1 reserved the terminating verdict for
F1/F4 because those "do not route to more tape" — implying F2/F3 might. Combined
with §10's pre-authorisation for "a later study to sweep any of them under its
own pre-registration", an F2 failure had a standing route back via a swept
admission cut-off, quantile, or ladder span. With G-02 already **NO-GO**, that is
the accumulated-near-miss channel §11 Q6 names.

Pre-declared: an **F2 or F3 failure at ≥2 cities also terminates**, unless the
failure is attributable to a cause **named in this document before computation**.
[D1], [D2], [D4] and [D5] qualify, because they are named here. A post-hoc "the
cut-off was wrong" does **not**.

*§12.3's seasonal fallback* fires "on the cell count, before any rate is read"
but revision 1 gave no count — a blank in a pre-registration is unenforceable.
Pre-declared: the fallback fires below **150 city-days** per monthly cell.

---

### 15.1 Folded without independent gating

The following are adopted in this revision but were not part of the blocking
set. They are recorded so the revision is complete, not so the count is larger.

- **M1** — F1/F4 firing at ≥2 cities under **LAG = 45** is reported as a
  pre-declared **LAG-CONTINGENT NO-GO in the headline**, not a sensitivity
  footnote. Revision 1 let LAG = 45 downgrade a pass but never fire a criterion.
- **M2** — Holm is implemented as the standard **step-down** procedure: order
  the 8 p-values ascending, compare the `i`-th against `α/(8 − i + 1)`, and once
  a test fails to reject, **retain all lower-ranked tests**. `CONTAM` correctly
  stays outside the family as a thresholdless diagnostic. F4 is outside
  multiplicity control and is stated as such, since it carries the terminating
  verdict across 4 cities; the "2-of-4" composite has no declared error rate and
  is likewise stated as a declared judgement, not a controlled test.
- **M4** — §12.1's "neither is measurable from this archive" is **overstated**
  for incidence. The archive rows carry raw METAR text containing the `COR`
  token, and out-of-order `valid` sequences are directly detectable. A
  descriptive panel reports **COR incidence and out-of-order-arrival incidence
  per city**; the *magnitude* of retraction risk remains a named unbounded risk.
- **M6** — the parent's absolute floors (≥1,000 retained city-day bucket cases
  per city, ≥5,000 total;
  `settlement_bucket_guard_band_prereg_2026-08-26.md:70-73`) are **retained in
  addition to** §8.3's precision floor. Revision 1 substituted the precision
  floor silently.
- **M7** — the §5.1(3) `M_final` equality check is pinned to **unrounded-tenths**
  equality, with an expected mismatch count of **zero**; any mismatch halts.
- **M9** — all quantiles, for both `R̂` and F4, use the **nearest-rank**
  estimator.
- **L1** — §8.3's LEAK precision floor (n ≈ 62) is non-binding by roughly two
  orders of magnitude against ~3,500 boundary cases per city and is described as
  such. The real precision constraint is [D3], not `n`.
- **L2** — `DecisionSnapshot` asserts `T ∈ {10:00, 13:00, 16:00} LST` on the
  evaluation path, so §5.1(3)'s end-of-climate-day construction cannot leak into
  evaluation.
- **L3** — the §6.1(5) import-linter contract additionally forbids
  proxy → any module exposing `daily_maxima` or `CliLabel`, which is the actual
  shortest leak path.

### 15.2 What this revision does not change

The review found the following sound, and they are carried forward untouched:

- The **inversion of the brief's question** (§2) is legitimate in form: exclusion
  is the operationally meaningful question, `LEAK` is correctly promoted to
  primary, the full 5×5 confusion matrix is retained so recovery remains
  measured. Its *premise* is corrected by [D5], not its logic.
- The **[R8] non-transfer argument** (§6.4) is correct and correctly scoped. The
  parent's invariance holds because its statistic is determined by the ordered
  sequence, so a uniform shift is a no-op; `M_obs(c,d,T)` is cut at an exogenous
  wall-clock `T`, so the shift changes set membership, deleting the ~9–10 most
  informative reports in `(T − LAG, T]`.
- The **ladder substitution itself** (§5.3) is mandatory and right. Only the
  rules transcribed around it were invalid.
- The **primary-cell pinning** (§8.1, §8.2) is a genuinely closed selection
  surface: NYC excluded in advance and irreversibly, MDW retained so it can fail,
  secondary `T` forbidden from rescuing a primary, no best-`T`, quantile
  explicitly un-sweepable.
- **§9.2's scoping** — that a pass is "a licence to ask a better question, not to
  place an order" — and §8.3's pre-declared prediction, recorded so its
  confirmation cannot be sold as a finding.
- **§12.2's** venue-ladder under-estimate argument, as noted in [D10].

### 15.3 The risk this revision is guarding against

The review's closing observation is recorded here because it inverts the
expectation the brief was written under. As specified in revision 1, this study
was more likely to **over-kill** than to rescue: terminating on F4's mismatched
statistic ([D7]) or on a `LEAK` inflated by [D2]'s laundering defect, and then
attaching §9.1's over-broad "regardless of any tape" language to that result.

A wrong terminating verdict on a strategy that may well deserve to die is still
a wrong verdict, and it would be recorded in this programme as settled fact.
[D2], [D4] and [D7] exist to prevent that, and [D10] exists to prevent the
opposite.
