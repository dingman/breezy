# `cli_settlement_print_lock` — REFUTED on real venue data (2026-09-01)

First economically admissible run in the programme. Nautilus produced the
result; nothing here was hand-computed.

## What Nautilus emitted

    condition    strategy                   status     orders fills  realized_pnl   balance
    live_capture cli_settlement_print_lock  COMPLETED       0     0        +0.00   10000.00

Account `AccountType.CASH`, base USD, starting balance 10,000.00 (the shipped
`STARTING_BALANCE_USD`, not an operator control). Engine ran
2026-08-31T20:37:55Z -> 2026-09-01T14:01:02Z, 0 ERROR lines, 30 instruments
subscribed, 15 `NwsClimateDay` elements delivered. The wiring positive-control
test passes, so this is not a mis-wired quiet run.

## Data provenance

10.5h continuous capture, 2026-09-01T03:30:34Z -> 14:01:01Z, clean `DISPOSED`.
Preflight: **671552 rows, 298 files, 297 intact, 1 empty, 0 truncated,
0 unreadable, exit 0**. This is the first capture whose integrity was verified
rather than assumed (BL-23).

The tape holds BOTH climate days, 30 instruments each. The `2026-08-31` ladders
are the first ever recorded across the hours their FINAL CLI prints arrived --
the overlap `FEEDBACK_FOR_GROK_2026-08-31.md` §1 measured as ZERO.

## THE FINDING (N3) — the winning bucket is bid-only

Verified twice: by the dispatched agent, and independently by the main session
reading `OrderBookDepth10` through the NATIVE `ParquetDataCatalog.query`.
Identical counts.

| Station | winning rung | depth rows | rows with an ASK | rows with a BID |
|---|---|---|---|---|
| NYC | `gte78lt79f` | 335 | **0** | 335 |
| MIA | `gte91lt92f` | 403 | **0** | 403 |
| MDW | `gte91lt92f` | 777 | **0** | 777 |
| LAX | `gte78lt79f` | 962 | **0** | 962 |
| SFO | `gte66lt67f` | 855 | **0** | 855 |

**0 of 3332 pooled rows offered anything.** Raw NYC level-0:
`bids[0] = 0.99 x 7682.70`, every ask level `0.00 x 0.00`. The losing rungs are
the exact mirror: `asks[0] = 0.01 x 21986.73`, bid side empty.

Bucket mapping was CORRECT on all five stations -- the printed value landed in
exactly one rung with `contains=True`. The strategy identified the right
contract every time and could not buy it.

**Interpretation.** Once the final print is public the contract is known to pay
$1. Nobody offers it; the book is a queue of buyers at 0.99. A LONG-ONLY TAKER
HAS NOTHING TO LIFT. This is not a config defect, a gate, or a bug. It is market
structure, and it refutes the thesis that "the book has not yet absorbed the
print". The book absorbs it completely.

## The second, independent null (N0) — no legal window either

Every `2026-08-31` final printed AFTER its own market's `endDate`, so
`hours_to_settlement` was already negative at every print instant (-0.649h MDW
to -8.549h MIA). All 42 final-print pairs (7 finals x 6 rungs) stopped at
`halt_window`; 48 more at `no_quote` (prints before the tape opened). ZERO
reached the decision layer, which is why `RefusalCounter.counts` is EMPTY --
precisely the blindness BL-19 §8.5 predicted. The 90 persisted decision records
are what makes this null decodable instead of mute.

Both nulls independently kill the same window. Even granting a legal window,
there was no ask.

## OPEN VENUE QUESTION — do not close this by assumption

The strategy measures the deadline against `expiration_ns`, mapped from the
venue's `endDate` (`parsing.py:1202`). But the venue documents settlement at
08:00 ET while `endDate` here was 05:00-08:00Z, and the captured
`VenueSettlementSnapshot` shows books still updating -- with LAX and SFO
briefly back to `MARKET_STATE_OPEN` 11:14-12:36Z -- hours AFTER `endDate`. If
`endDate` is trading-close and settlement is a separate later instant, the halt
arithmetic is measured against the wrong clock. This does NOT rescue the
strategy (N3 is independent of it) but it may matter to any successor.

## What this does and does not establish

ESTABLISHES: the post-final-print window is unharvestable by a long-only taker
on all five stations, on real data, with the tape's integrity verified.

DOES NOT ESTABLISH: that these markets have no edge. This tests exactly one
window -- the one AFTER settlement information became public. The natural next
question is whether the eventually-winning rung carried an ask BEFORE its final
printed. Today's tape already holds the intraday `2026-09-01` books; their
finals print 2026-09-02 05:00-13:00Z and will label them. That experiment needs
no new capture design, only tomorrow's prints.

Artifact: `~/.local/share/breezy/derived/strategy-backtests/print_lock_live_capture_20260901T142458+0000.json`
