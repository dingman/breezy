# H2 (open lower tail) REJECTED — and the structural lesson that replaces it

Date: 2026-09-01. Design critique (Grok) + independent verification against
`derived/settlement-truth/settlement_truth.csv` (N=9079 paired finals) and the
live capture `3dd59abf`. No trades, no backtests.

## H2 as proposed

After the CLI preliminary prints H, buy YES on an open LOWER tail `< X` with
`X > H`, on the reasoning that the running max is past the heating peak and a
one-sided, margin-conditioned hazard `d = X - H` can be measured as the mirror
of the upper-tail table.

## Rejected on two independent grounds

### 1. Empty listed support — trigger fired 0/4

Same-day listed lower cutoffs vs the printed preliminary (2026-08-31):

| Station | H | listed `ltXf` | H < X? |
|---|---:|---:|---|
| MDW | 91 | 89 | NO (-2) |
| MIA | 91 | 87 | NO (-4) |
| NYC | 78 | 78 | NO (0, `lt78` needs tmax<=77) |
| SFO | 67 | 64 | NO (-3) |

Verified directly against the captured instrument list. Median YES ask on those
breached lower tails: 0.01. Correctly priced non-events — the exact DUAL of
reading a 0.02 unreached-upper-tail ask as H1 edge.

An error in the H2 brief, corrected: its worked example paired Aug-31's H=78
with Sep-1's `lt82f` ladder. Same-day, NYC's lower tail was `lt78f`. Mixing a
cooler day's max with a warmer day's ladder is not the post-preliminary geometry.

### 2. The 97% upward asymmetry IS H2's loss function

H1 loses only on a DOWN crossing (0.21%). H2 loses whenever the rise reaches d.
Reproduced independently, N=9079: P(up)=6.895% (626), P(down)=0.176% (16),
up-share of all changes 97.5%. Max rise +17F.

Wilson-95% LOWER of P(rise < d), pooled:

| d | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| lower | 0.9257 | 0.9712 | 0.9836 | 0.9908 | 0.9934 | 0.9954 | 0.9966 |

Per station (Wilson lower):

| | d=1 | d=2 | d=3 | d=4 | d=5 |
|---|---|---|---|---|---|
| LAX | 0.984 | 0.988 | 0.991 | 0.995 | 0.995 |
| MIA | 0.955 | 0.989 | 0.996 | 0.998 | 0.998 |
| SFO | 0.946 | 0.976 | 0.981 | 0.989 | 0.991 |
| NYC | **0.868** | 0.939 | 0.968 | 0.978 | 0.984 |
| MDW | **0.846** | 0.943 | 0.965 | 0.981 | 0.986 |

A 0.99-class lock needs d>=7 pooled, d>=6-7 on MDW/NYC. The listed same-day d
was <= 0 on 4/4. **The intersection of "safe d" and "listed d" is empty.**
Rejected without needing an economic test.

## THE STRUCTURAL LESSON

A six-rung ladder centred on the forecast is a WINDOW AROUND THE EXPECTED MAX.
The interiors catch the mode; both open tails are the outlier rungs. So an
observation lock on EITHER tail is an outlier strategy by construction:

    H1 (upper tail) fired 0/4.   H2 (lower tail) fired 0/4.

The day lands in the interiors. That is what the ladder is designed to do.

## What replaces them: wait for the FINAL print

`cli_settlement_print_lock` (BL-13, specified, unimplemented) triggers on the
FINAL CLI print and buys YES on the unique bucket CONTAINING the printed value —
usually an interior. This resolves the apparent contradiction with G-01:

- Interiors are dead AFTER THE PRELIMINARY, because prelim->final revision
  breaks exact equality (MDW 13.96%, NYC 11.79% Wilson-upper > 0.05).
- Interiors are SOUND AFTER THE FINAL, because the revision has already
  happened. Measured p_stable (first final -> last pre-settlement) is 99.989%
  (9105/9106); halt-window 98.66% (9041/9164).

The trigger is "a final exists and >= 2.0h remain", which is designed to fire on
most station-days rather than on outliers. It is long-only, taker, needs no
forecast, and the exclusive-bucket logic already exists in `RiskManager`.

**Its clock window is 05:00-13:00Z, NOT 19:00-01:00Z.** Evening capture measures
how often either tail is reachable; MORNING capture is what tests the strategy
that can actually fire.

## Pre-registered kill for the tail-locks (cheap, no capture campaign)

Trigger rate over captured station-days with a printed preliminary; dead below
0.20. Currently 0/4 for H1 and 0/4 for H2. Do NOT kill on "median ask vs
break-even" without first gating on the trigger condition — that comparison is
meaningless on an unfired tail and will read pennies as certainty.
