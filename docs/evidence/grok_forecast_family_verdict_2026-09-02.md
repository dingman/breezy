# Grok design memo — the forecast family under honest forecast error (2026-09-02)

Strategy design is routed to Grok by standing operator instruction. This memo is Grok's
verbatim output to the brief at the end of this file, produced read-only
(`--permission-mode plan`, `--disallowed-tools spawn_subagent`) against the tree at
`a46751d`. Claude's role: brief, verify against the artefact, implement. Verification
notes and the decisions taken from it are in `docs/core/PROGRESS.md`.

---

**Kill it. Honest sigma, an empty bid, uncalibrated priors, and no forecast ingest leave no defensible live-small book; prior edges were manufactured.**

## Invariants (binding)
Nautilus is immutable. `allow_short` stays `False` (long-only; every sell reduces). Do not weaken safety/settlement/barrier/contract tests. Do not assign operator-reserved controls (max daily budget, `max_position_contracts`). Do not touch live-trading enablement or the NO-SEND firewall. The bot has never sent a live order.

## 1. Viability under honest sigma
Model: Gaussian, `p_floor=0.01`, continuity correction 0.5. CONUS summer bins (`default_conus_summer_error_model`): σ(3h)=1.4, 6h=1.7, 12h=2.1, **24h=2.8**, 36h=3.3, 48h=3.7. Fee `θ·a·(1−a)` with **θ=0.06** (729/729 captured markets). Break-even at a 5¢ ask ≈ **0.0629** (fee 0.00285 + 1¢ tick). Long-YES: `model_p = Φ((d+0.5)/σ)` clipped to [0.01, 0.99], `d = forecast − threshold` on an open upper tail.

T-11 pin (verified in `test_forecast_sigma_uses_issuance_lead.py`): NYC ≥80°F, forecast 83.0, issued T−24h, ask 0.80, cost **0.015** → σ 1.4→2.8, `model_p` 0.99→**0.894**, edge **0.175→0.079**. At ask 0.85 honest edge **0.029 < 0.06**; the defect manufactured the trade.

**Ask / distance at 24h (σ=2.8), open tail, gate `model_p ≥ ask + 0.075`:**

| `d` (°F) | `model_p` | max ask to clear 0.06 | EV>0 ask (fee+1¢ slip) |
|---:|---:|---:|---:|
| 1.9 | 0.80 | 0.725 | ~0.78 |
| 3.0 | 0.894 | 0.819 | ~0.87 |
| 4.1 | 0.95 | 0.875 | ~0.93 |
| ≥6.0 | 0.99 clip | **0.915 hard cap** | ~0.97 |

At 48h (σ=3.7) the same 0.894 needs **d≈4.1°F**. Interiors are 2°F closed rungs `[A,A+1]`. Peak `model_p` at σ=2.8 is **~0.28** (forecast dead-center). Clearing 0.06 requires **ask ≲ 0.20**. Efficient interiors should sit near 0.28; residual EV is a couple of cents, inside noise.

**`min_entry_edge=0.06` is an artifact.** It was a screen that still admitted manufactured 0.175 edges. The engine’s own `expected_probability_se` at the T-11 point is **~0.10** — larger than 0.06 — and is **not used** as a gate. Sigma is an **unfitted prior** (“not claimed NWS statistics”). A defensible bar is ≳ that SE plus a calibration buffer, **~0.10–0.12**. The honest 0.079 example fails it.

Further cuts, verified in code:
- Live `ForecastMispricingStrategy` builds `ForecastErrorModel` **without** `sigma_by_key` (parametric 24h σ≈**2.91**, slightly worse) and still prices with flat `transaction_cost_prob=0.015`, **not** `venue_fee_prob`. BL-19’s structured fee was applied to `running_extreme_lock` only.
- `stale_forecast_hours=8`: a T−24h print read at T−3h is `stale_forecast` → FLAT. The T-11 trade does not even form unless a **newer issuance** exists.
- `issuance_lead_hours` uses venue `expiration_ns`, not time-to-high. Venue settlement is **08:00 America/New_York next morning**; the high locks mid-afternoon. Using endDate as sigma’s deadline is conservative vs met-lead (UNVERIFIED how `expiration_ns` maps to `endDate` on every slug).
- **Breezy ingests no forecasts.** `ForecastSource` is a required injection; `FORECAST_INGESTION_PLAN.md` is unbuilt. Existing backtests use a **synthetic** snapshot. Those numbers are void twice: wrong sigma, and no real forecast.

**Plain answer:** at the leads a real NWS day-ahead/morning forecast actually has (σ≈2.1–3.7), the family has **little or no defensible edge**. The remaining pocket is an open tail, forecast ≳3–4°F in-the-money, ask still ≲0.80, held to settlement. That set is likely empty once the book sees the same forecast. Do not fund it.

## 2. Exit policy (T-9)
**Hold to settlement. Never dump.** `halt_hours_before_settlement=1.0` is measured against administrative `endDate`, not met lock, and is UNVERIFIED against data. `_flatten` → `close_all_positions` into a **median ~0.3-contract bid**. `running_extreme_lock` already treats halt as **entry-only**; the forecast family should match that.

- **Cancel** working buys at met lock (running high in-bucket, or final CLI) — cancel, not sell. Today `flatten_on_observation=False`.
- **Do not flatten a winning long.** Sunk ask+fee; hold EV is `model_p`; selling 0.3 lots donates the rest.
- **Do not flatten a loser either**, unless a bid exists with **size ≥ the position** (or a material slice) at `bid − exit_fee > residual model_p`. With 0.3-lot bids that never happens. A 25–150 lot market sell walks toward 0.01.
- `mispricing_exit_long` (`exit_edge=0.015`) is the same dump. Disable it on this book.
- `min_liquidity_contracts=25` vs `min(bid,ask)` (OQ-10) blocks two-sided QuoteTicks; Depth10 one-sided asks can still enter. Exits remain unexecutable.

**Validation (tape + NWS, no live orders):** join Depth10 bid size/price vs (a) hours to venue `endDate`, (b) hours after local mid-afternoon / after CLI `is_final`. Report, per station-day: fillable sell fraction of a 25-lot, VWAP vs eventual $0/$1, and PnL(hold) − PnL(flatten-at-halt). Expect hold ≫ flatten on in-the-money tails.

## 3. Kill criteria
Any one is enough:

1. **Paper join (no orders):** real issuance-lead forecasts × tape asks × NWS tmax. Taken-trade hit rate has Wilson 95% **upper** bound below `ask + θa(1−a)`. **n≥150** independent settlements if typical `p~0.8`; **n≥60** if claimed `p≥0.9` and realized ≤0.75.
2. **Operational empty book:** 30 climate-days × 5 stations (**150 station-days**) with a real `ForecastSource`, **zero** trades clearing honest σ and real fees.
3. **Calibration:** RMSE(forecast vs CLI tmax) at used leads **>1.3×** model σ (e.g. 24h RMSE > **3.6°F** vs 2.8). Then every `model_p` is overconfident.

## 4. Measure before live-small (ranked)
1. **Is σ even right, and at which leads would a forecast exist?** Dominates EV. Prior, not a fit; no ingest. **Partially from existing data:** Open-Meteo previous-runs (OQ-2, 2022–23) + NWS settlement archive. **Not** from the quote tape. Live orders not required. A production `ForecastSource` does not exist.
2. **Do honest-σ trades exist on the book?** Needs forecast archive × tape asks × 2°F/tail facts. Tape exists; forecasts do not. Live orders not required for the join.
3. **Adverse selection / whether those asks are liftable.** Tape already says 57% of $24.53 orders exceed level-0; p90 walk **0.137** (BL-25). `slippage_prob` is UNMEASURED. Walk-the-book: tape. Pull-when-lifted: **live orders**.

Do not spend live-small budget answering (1) or (2).

**UNVERIFIED:** station-level σ/bias; exact `expiration_ns`↔`endDate` per slug; whether `gteAlitBf` always decodes to `[A,A+1]` on live instruments; bid-size distribution **including** one-sided books (OQ-13 conditions every bid stat on two-sided quotes); whether any live `ForecastSource` will exist at <12h met-lead.


---

## The brief Grok answered

> # Strategy design brief — the forecast family under honest forecast error
> 
> You are the strategy designer for Breezy, a weather-prediction trading bot on Polymarket.us
> built natively on Nautilus Trader. Repo is at your working directory. READ-ONLY: analyse and
> design; write no files. Output a design memo to stdout, under 900 words, headed by a one-line
> verdict.
> 
> ## Hard invariants (restate in your memo; never propose violating them)
> - Nautilus Trader is immutable — never modify, patch, fork or reimplement anything under
>   `.venv/**/nautilus_trader/`; assume it already provides what is needed until proven otherwise.
> - `allow_short` stays `False`. Long-only. Every sell reduces.
> - Never weaken or delete a safety, settlement, barrier or contract test.
> - Never assign a value to an operator-reserved control: max daily budget, `max_position_contracts`.
> - Never touch live-trading enablement or the NO-SEND execution-egress firewall.
> - The bot has NEVER sent a live order. Nothing here is live.
> 
> ## The market
> Daily high-temperature buckets (e.g. "NYC high >= 80F") for NYC/MIA/MDW/LAX/SFO, settling on the
> NWS climate day. Binary contracts paying $1. Taker-only venue fee `theta * contracts * p * (1-p)`
> at the executable price (`src/breezy/strategy/weather_common/costs.py`), break-even at a 5c ask
> about 0.0629. **The bid side is essentially empty: measured median top-of-book bid is ~0.3
> contracts.** Exits by selling are therefore mostly not executable; a position is effectively
> held to settlement unless it can be flattened at a real bid.
> 
> ## What just changed, and why it voids every prior edge estimate
> `ForecastErrorModel.sigma(location, date, horizon_hours)` in
> `src/breezy/strategy/weather_common/probability.py` models forecast error as a function of lead
> time. Until today every call site passed the LIVE hours-to-settlement, so a forecast issued at
> T-24h and read at T-3h was scored as a 3-hour forecast: sigma ~1.4F instead of ~2.8F.
> Fix (T-11, committed): sigma now receives the ISSUANCE LEAD, `hours_until(deadline,
> forecast.published_at)`.
> 
> Measured consequence on one bucket (NYC high >= 80F, forecast 83.0F published T-24h, read T-3h,
> ask 0.80, default CONUS summer error model): sigma 1.4 -> 2.8, model_p 0.99 -> 0.894,
> edge 0.175 -> 0.079. Edge was overstated 2.2x. At ask 0.85 the honest edge 0.029 is BELOW
> `min_entry_edge` 0.06 while the understated 0.125 cleared it — **the defect manufactured
> trades that should not have existed.** Every prior forecast-family backtest number is void.
> 
> Read: `probability.py` (the sigma model and its horizon bins), `costs.py`,
> `src/breezy/strategy/forecast_mispricing/decision.py` and `config.py`,
> `src/breezy/strategy/weather_common/risk.py` (`evaluate_order`), and
> `docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md` sections T-9 and T-11.
> 
> ## Design questions — answer each, concretely, with numbers where the model permits
> 1. **Viability under honest sigma.** For the forecast_mispricing family, derive analytically —
>    from the error model's sigma-by-lead bins and the fee — the ask range and forecast-vs-bucket
>    distance at which expected value after fees is positive. Is `min_entry_edge = 0.06` the right
>    threshold, or an artifact of the understated sigma? State what a minimum defensible threshold
>    is and why. If the honest answer is that the family has little or no edge at the leads at
>    which forecasts are actually available, say so plainly.
> 2. **Exit policy (finding T-9).** Today `halt_hours_before_settlement = 1.0` is measured against
>    the venue's administrative `endDate`, not the meteorological lock of the daily high (mid-
>    afternoon local), and `_flatten` dumps via `close_all_positions` into that ~0.3-contract bid.
>    The codebase disagrees with itself: `running_extreme_lock` treats the halt as ENTRY-ONLY and
>    never flattens; the forecast family flattens unconditionally. Design the correct exit policy
>    for a long-only book on an empty bid: when, if ever, should a position be flattened rather
>    than held to settlement? Should it differ for a winning vs losing position? Specify the
>    measurement, from the quote tape plus NWS settlement, that would validate your policy.
> 3. **Kill criteria.** State the observation — from live capture or live-small trading — that
>    would refute the forecast family outright, with the sample size needed to make it decisive.
> 4. **What must be measured before live-small.** Rank the top three unknowns whose resolution
>    most changes the expected value, and say which of them can be answered from existing data
>    (the quote tape at `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us` and the
>    NWS settlement archive) versus needing live orders.
> 
> Be adversarial toward the family. The operator would rather kill it now than fund it on a
> manufactured edge. Mark anything you could not verify in the code as UNVERIFIED.
