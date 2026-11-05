# First in-window capture — H1's trigger did not fire once

Date: 2026-09-01. Capture 00:41:05Z–00:59:54Z (18m49s), attended, read-only
market data. Clean shutdown (`DISPOSED`). 62 MB, 10088 depth records, 60
instruments across all five stations and two climate days. Converted to the
catalog with the native `convert_stream_to_data`.

This is the FIRST capture Breezy has ever taken inside the 19:00–01:00Z
preliminary window. The prior tape was 6m09s at 16:05Z with zero overlap.

## What the capture validated

- **BL-18's fix works against the live venue.** The log shows, per instrument,
  `Could not parse quote ... VenuePayloadError` immediately followed by
  `Created order_book_depths writer ...`. One-sided books now record depth while
  correctly refusing to form a two-sided quote. Before the fix the frame was
  discarded whole.
- **The 60 `cache.instrument(...) is None` ERRORs are cosmetic.** The check runs
  immediately after publishing instruments with no `await`
  (`data.py:720-721`), so the data engine has not had an event-loop turn. The
  authoritative gate runs after `await` (`data.py:724`) and passed — all 60 then
  logged `subscribing ... (new)`. WS frames resolve instruments via
  `_instrument_provider.find()` first, cache only as fallback
  (`data.py:1020-1022`), so records never depended on that lookup. Data is
  sound. The log noise (60 ERRORs per discovery cycle) should still be fixed
  before an unattended run, or it will bury real errors.

## THE FINDING: H1's trigger fired ZERO times

| Station | 2026-08-31 preliminary tmax | Listed upper-tail floor | H >= X? |
|---|---|---|---|
| MDW | 91F | >= 97F | NO (-6) |
| MIA | 91F | >= 95F | NO (-4) |
| NYC | 78F | >= 86F | NO (-8) |
| SFO | 67F | >= 72F | NO (-5) |
| LAX | no record captured | >= 80F | unknown |

Measured asks on those upper tails (size-0 pads excluded per BL-20), n=1824:

| Station | Date | Floor | n | min | median | max |
|---|---|---|---|---|---|---|
| LAX | 08-31 | 80 | 122 | 0.0200 | 0.0200 | 0.0300 |
| LAX | 09-01 | 84 | 119 | 0.0100 | 0.0100 | 0.0200 |
| MDW | 08-31 | 97 | 66 | 0.0100 | 0.0100 | 0.0100 |
| MDW | 09-01 | 95 | 928 | 0.2000 | 0.2100 | 0.2100 |
| MIA | 08-31 | 95 | 66 | 0.0100 | 0.0100 | 0.0100 |
| MIA | 09-01 | 95 | 114 | 0.0200 | 0.0200 | 0.0200 |
| NYC | 08-31 | 86 | 66 | 0.0100 | 0.0100 | 0.0200 |
| NYC | 09-01 | 90 | 124 | 0.0100 | 0.0200 | 0.0200 |
| SFO | 08-31 | 72 | 66 | 0.0200 | 0.0200 | 0.0200 |
| SFO | 09-01 | 72 | 153 | 0.0900 | 0.0900 | 0.0900 |

**100% of these asks sit below the 0.99663 break-even, and that fact is
MEANINGLESS as a signal.** The break-even derives from `p_model = 0.996829`,
which holds ONLY once the observation has already satisfied the tail. None had.
These asks are the market correctly pricing tails the day did not reach.
Treating "ask 0.02 < break-even 0.99663" as an entry would buy a contract
needing 6F more heat while believing it 99.7% certain. Any future analysis of
this strategy MUST gate on `H >= X` before comparing an ask to a break-even.

## What this does to H1

It confirms the strategy-design critique that the **listed** tail is not the
**proxy** tail. The venue lists exactly ONE `gte<N>f` per city-day, positioned
ABOVE the expected max (here 4-8F above the day's actual). The margin-
conditional Wilson table (`observation_lock_falsification_2026-08-31.md` s2) was
built by sweeping every integer floor in `[H-5, H]` — floors the venue never
lists. So the table describes a population the strategy cannot trade.

H1 as specified requires the day to BEAT the ladder's top rung. That is a
hot-outlier event, not the routine post-preliminary lock the brief assumed.
Trigger frequency, not edge size, is now the binding question — and on five
station-days it was zero.

**Not yet falsified, but materially weakened.** N=5 station-days cannot
establish a base rate. The open question for the next design iteration: how
often does the daily max exceed the venue's listed top rung? Historical
Polymarket listings are unavailable, so this cannot be answered from the
archive directly and needs either forward capture or a defensible proxy for how
the venue positions the top rung.

## Caveat on timing

The window sampled 00:41–01:00Z, hours AFTER the Aug 31 preliminaries printed
(~20:32–20:50Z). If a repricing window exists after a print, this capture is
downstream of it. A quiet tape here is therefore weak evidence against the
latency premise; asks below break-even on a SATISFIED tail would have been
strong evidence for it. Neither was observed, because the trigger never fired.
