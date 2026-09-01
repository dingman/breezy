# H4 preliminary economic read — is the h=1 rung offered at the trigger?

Generated 2026-09-01T18:51:04+00:00 from
`scripts/analysis/h4_preliminary_economic_read.py`.
Climate day: **2026-08-31**. Strategy: `docs/strategies/H4_headroom1_afternoon_lock.md`.

## 0. What this is, and the bounds on reading it

A descriptive measurement over ONE climate day. It is **not** a backtest,
**not** a trading simulation and **not** a profitability evaluation: no order,
fill, position, fee, P&L or return appears anywhere in the pipeline that
produced it. NautilusTrader is the exclusive owner of backtesting and
execution. The ask VWAP below is a price statistic over a captured ladder — a
property of the book, not a trade.

**`n = 4` station-days on one climate day.** This design CAN REFUTE — you
cannot buy what is not offered, and an absent ask at the trigger is decisive —
but it CANNOT CONFIRM. The settling-rung hit/miss at the end is an ANECDOTE
and is labelled as one.

### Tape integrity (LESSONS L-8) — verified BEFORE interpretation

A truncated Arrow stream is silently dropped by the native reader: 0 rows, no
exception, no log line. A 0-row result is ambiguous between *quiet market* and
*lost tape* by construction, so the preflight is a required input here, not a
convenience. `breezy-quote-tape-preflight` reports, for this climate day:

> breezy-quote-tape-preflight over ~/.local/share/breezy/catalog/quote_tape/polymarket_us, run 2026-09-01: all 346 staged files carrying 2026-08-31 instruments are INTACT — 90462 rows, 0 truncated, 0 unreadable, 0 empty. (The global run also reports 4 TRUNCATED files; all 4 are 2026-09-01 instruments of the still-running capture instance 5a111bca and are mid-flush, not lost. None carry 2026-08-31 data.)

Depth catalog: `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`
ASOS archive cache: `/home/jon/.local/share/breezy/archive/settlement-alignment-cache`

## 1. Capture coverage against each station's trigger window

Trigger hours are H4's pre-registered values in LOCAL STANDARD time. The
capture window is the same wall-clock interval everywhere; its LST rendering
differs by station, which is what decides who has evidence and who does not.

| station | trigger (LST) | capture start (LST) | capture end (LST) | trigger window observed? | hours of window missed BEFORE capture | hours missed AFTER capture |
|---|---:|---|---|---|---:|---:|
| LAX | 18:00 | 2026-08-31 16:40:55 | 2026-08-31 16:59:52 | **NO — not observed at all** | n/a — whole window unobserved | n/a |
| MDW | 16:00 | 2026-08-31 18:40:38 | 2026-08-31 18:59:44 | yes (tail only) | 2.68 | 5.00 |
| MIA | 14:00 | 2026-08-31 19:40:59 | 2026-08-31 19:59:40 | yes (tail only) | 5.68 | 4.01 |
| NYC | — (excluded) | 2026-08-31 19:40:59 | 2026-08-31 19:59:53 | n/a — excluded from H4 | n/a — whole window unobserved | n/a |
| SFO | 15:00 | 2026-08-31 16:40:43 | 2026-08-31 16:59:45 | yes (tail only) | 1.68 | 7.00 |

* **LAX** — capture never reaches the 18:00 LST trigger: it ends at 16:59 LST, 1.00h short
* **MDW** — trigger 16:00 LST; observed 18:40-18:59 LST; 2.68h of the window before capture start and 5.00h after capture end are NOT observed
* **MIA** — trigger 14:00 LST; observed 19:40-19:59 LST; 5.68h of the window before capture start and 4.01h after capture end are NOT observed
* **NYC** — no trigger hour: this station is outside H4's universe, so it contributes no trigger evidence in either direction
  * excluded by H4 universe (instrument basis); measured and reported, never counted in the verdict.
* **SFO** — trigger 15:00 LST; observed 16:40-16:59 LST; 1.68h of the window before capture start and 7.00h after capture end are NOT observed

## 2. THE MEASUREMENT — did the entry condition hold, and was it offered?

Restricted to captured instants at or after the station's trigger hour, on the
target climate day. `R(t)` is the ASOS running maximum in whole °F using only
observations at or before `t`.

| station | instants at/after trigger | with `h == 1` | share | of those, carrying an ask | share | h distribution over the window |
|---|---:|---:|---:|---:|---:|---|
| LAX | 0 | 0 | n/a | 0 | n/a | — |
| MDW | 375 | 375 | 100.00% | 0 | 0.00% | h=1: 375 |
| MIA | 381 | 381 | 100.00% | 0 | 0.00% | h=1: 381 |
| NYC | 0 | 0 | n/a | 0 | n/a | — |
| SFO | 372 | 372 | 100.00% | 0 | 0.00% | h=1: 372 |

Where the entry condition never held, that is **kill-criterion 3a evidence**
about the trigger, not an economic result: there was nothing to price.

## 3. Ask prices on the `h == 1` rung

Depth-aware VWAP for a **$24.53** notional (the cost basis already
derived in `docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`),
walking the captured ask ladder in whole contracts — never level 0 alone.
`depth-limited` means the ladder ran out before the notional was absorbed.

**No `h == 1` rung carried an ask at any captured instant at or after any
station's trigger hour.** There is no price distribution to report — that
absence IS the measurement.

## 4. Ask availability across the whole captured ladder

Context for §2/§3: was the ask side empty only on the `h == 1` rung, or
everywhere? Counted over every captured depth snapshot on the target day,
including instants before the trigger hour.

| station | rung | closed interval | snapshots | with an ask | share | min ask | max ask | settling rung? |
|---|---|---|---:|---:|---:|---:|---:|---|
| LAX | lt72f | ≤71 | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| LAX | gte72lt73f | [72, 73] | 65 | 65 | 100.00% | 0.0100 | 0.0100 |  |
| LAX | gte74lt75f | [74, 75] | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| LAX | gte76lt77f | [76, 77] | 67 | 67 | 100.00% | 0.0100 | 0.0100 |  |
| LAX | gte78lt79f | [78, 79] | 63 | 7 | 11.11% | 0.9900 | 0.9900 | **WINNER** |
| LAX | gte80f | ≥80 | 122 | 122 | 100.00% | 0.0200 | 0.0300 |  |
| MDW | lt89f | ≤88 | 69 | 69 | 100.00% | 0.0100 | 0.0100 |  |
| MDW | gte89lt90f | [89, 90] | 67 | 67 | 100.00% | 0.0100 | 0.0100 |  |
| MDW | gte91lt92f | [91, 92] | 58 | 0 | 0.00% | — | — | **WINNER** |
| MDW | gte93lt94f | [93, 94] | 67 | 67 | 100.00% | 0.0100 | 0.0100 |  |
| MDW | gte95lt96f | [95, 96] | 65 | 65 | 100.00% | 0.0100 | 0.0100 |  |
| MDW | gte97f | ≥97 | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| MIA | lt87f | ≤86 | 65 | 65 | 100.00% | 0.0100 | 0.0100 |  |
| MIA | gte87lt88f | [87, 88] | 64 | 64 | 100.00% | 0.0100 | 0.0100 |  |
| MIA | gte89lt90f | [89, 90] | 68 | 68 | 100.00% | 0.0100 | 0.0100 |  |
| MIA | gte91lt92f | [91, 92] | 54 | 0 | 0.00% | — | — | **WINNER** |
| MIA | gte93lt94f | [93, 94] | 72 | 72 | 100.00% | 0.0100 | 0.0100 |  |
| MIA | gte95f | ≥95 | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| NYC | lt78f | ≤77 | 67 | 67 | 100.00% | 0.0100 | 0.0100 |  |
| NYC | gte78lt79f | [78, 79] | 56 | 0 | 0.00% | — | — | **WINNER** |
| NYC | gte80lt81f | [80, 81] | 75 | 75 | 100.00% | 0.0100 | 0.0100 |  |
| NYC | gte82lt83f | [82, 83] | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| NYC | gte84lt85f | [84, 85] | 70 | 70 | 100.00% | 0.0100 | 0.0100 |  |
| NYC | gte86f | ≥86 | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| SFO | lt64f | ≤63 | 67 | 67 | 100.00% | 0.0100 | 0.0100 |  |
| SFO | gte64lt65f | [64, 65] | 66 | 66 | 100.00% | 0.0100 | 0.0100 |  |
| SFO | gte66lt67f | [66, 67] | 59 | 0 | 0.00% | — | — | **WINNER** |
| SFO | gte68lt69f | [68, 69] | 67 | 67 | 100.00% | 0.0200 | 0.0200 |  |
| SFO | gte70lt71f | [70, 71] | 66 | 66 | 100.00% | 0.0200 | 0.0200 |  |
| SFO | gte72f | ≥72 | 66 | 66 | 100.00% | 0.0200 | 0.0200 |  |

### 4.1 The settling rung against the rest of its own ladder

The single most legible pattern in §4, computed per station over every
captured snapshot on the target day. `uniquely unoffered` is only claimed
when the REST of the ladder was in fact offered — if nothing is offered
anywhere the venue simply went dark, and the winner's silence means nothing.

| station | settling rung | snapshots | with an ask | other rungs: snapshots | with an ask | winner ask share | other ask share | winner uniquely unoffered? |
|---|---|---:|---:|---:|---:|---:|---:|---|
| LAX | gte78lt79f | 63 | 7 | 386 | 386 | 11.11% | 100.00% | no |
| MDW | gte91lt92f | 58 | 0 | 334 | 334 | 0.00% | 100.00% | **YES** |
| MIA | gte91lt92f | 54 | 0 | 335 | 335 | 0.00% | 100.00% | **YES** |
| NYC | gte78lt79f | 56 | 0 | 344 | 344 | 0.00% | 100.00% | **YES** |
| SFO | gte66lt67f | 59 | 0 | 332 | 332 | 0.00% | 100.00% | **YES** |

Where those winner-side asks sit relative to the trigger hour — this
table spans every captured snapshot, not just the post-trigger tail:

- LAX offered its settling rung on 7 of 63 snapshots — every one of them before the 18:00 LST trigger, which this capture never reaches (§1). They are context, not H4 evidence.

## 5. Did the `h == 1` rung settle YES? — ANECDOTE, n = 4

Winners read from Breezy's own settlement store (`is_final=True`,
`is_superseded=False`), not from any external claim.

| station | settled tmax °F | non-superseded finals | settling rung | ASOS day max °F | `h == 1` rung at trigger | hit? | provenance |
|---|---:|---:|---|---:|---|---|---|
| LAX | 79 | 1 | tc-temp-laxhigh-2026-08-31-gte78lt79f.POLYMARKET_US | 79 | — (never held) | n/a — condition never held | `/home/jon/.local/share/breezy/catalog/polymarket_us/LAX` |
| MDW | 91 | 1 | tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US | 91 | tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US | **HIT** | `/home/jon/.local/share/breezy/catalog/polymarket_us/MDW` |
| MIA | 91 | 3 | tc-temp-miahigh-2026-08-31-gte91lt92f.POLYMARKET_US | 91 | tc-temp-miahigh-2026-08-31-gte91lt92f.POLYMARKET_US | **HIT** | `/home/jon/.local/share/breezy/catalog/polymarket_us/MIA` |
| NYC | 78 | 1 | tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US | 78 | — (never held) | n/a — condition never held | `/home/jon/.local/share/breezy/catalog/polymarket_us/NYC` |
| SFO | 67 | 1 | tc-temp-sfohigh-2026-08-31-gte66lt67f.POLYMARKET_US | 66 | tc-temp-sfohigh-2026-08-31-gte66lt67f.POLYMARKET_US | **HIT** | `/home/jon/.local/share/breezy/catalog/polymarket_us/SFO` |

With four station-days on one climate day this column cannot distinguish a
real hit rate from luck. It is recorded so it is not re-derived later, and it
is not evidence of anything on its own.

## 6. Input denominators

| station | ASOS obs on the climate day | ASOS day max °F | depth snapshots | ladder rungs | METAR rows dropped |
|---|---:|---:|---:|---:|---|
| LAX | 279 | 79 | 449 | 6 | missing_metar_t_group_row=13 |
| MDW | 319 | 91 | 392 | 6 | none |
| MIA | 305 | 91 | 389 | 6 | missing_metar_t_group_row=123 |
| NYC | 26 | 78 | 400 | 6 | missing_metar_t_group_row=6 |
| SFO | 316 | 66 | 391 | 6 | missing_metar_t_group_row=1 |

## 7. VERDICT — scoped to what `n = 4` on one climate day supports

**REFUTED_ON_OBSERVED_WINDOW**

at MDW, MIA, SFO the entry condition held and NO ask was present on the h==1 rung at any observed instant. Decisive for the OBSERVED portion of the trigger window only -- the hours before capture start are not evidence in either direction.

| | stations |
|---|---|
| condition held, NO ask on the h==1 rung | MDW, MIA, SFO |
| condition held, an ask WAS present | — |
| window covered, condition never held | — |
| trigger window not observed at all | LAX |
| outside H4's universe, contributing nothing | NYC |

### What this does and does not close

**Does.** For the observed tail of the trigger window, at every covered
station, the entry H4 specifies was not available: the rung was not offered,
at any price, in any size. An absent ask is not a pricing problem that a
better model or a lower break-even could solve.

**Does not.** The observed tail is a small fraction of each trigger window
(§1). H4's own thesis is that stay-probability rises through the afternoon
while the book empties, so the EARLY part of the window — the part not
captured — is precisely where an offer is most likely to survive. This run
cannot speak to it.

**Not measured here, by design.** No profitability, no return, no fee, no
fill and no P&L. Whether any observed price would have been *worth* taking is
a question for NautilusTrader, and it does not arise while the ask is absent.

