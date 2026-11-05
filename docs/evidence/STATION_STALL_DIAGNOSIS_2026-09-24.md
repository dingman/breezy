# LAX/MDW "station stall" on 2026-09-20: not a stall, a closed market

**Backlog item:** AUD-01b (plan `docs/plans/backlog/AUDIT_2026-09-21/AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md` §3, §5, §7, §8)
**Date:** 2026-09-24 · **Method:** READ-ONLY. Sources were the node log, the offer tape, the ingested quote-tape catalog, the observation store and the recorder journal. No process was signalled and nothing under `~/.local/share/breezy` was written.
**Code base cited:** `c527439` (worktree `backlog/aud-01b-stall-diagnosis-2026-09-24`)

## Verdict

| Station | 09-20 offer-tape rows | Plan §7 cause class | Measured cause |
|---|---|---|---|
| **MDW** | 0 | **(d) zero-eligible-snapshot day** | 0 of 334 in-window YES quotes had an ask inside the executable band `(0.05, 0.95)`. The market had already settled on the 69-70 °F rung, with asks of 0.98-0.99 on that rung and 0.02-0.04 on every other quoted rung. The strategy refused all 826 in-window evaluations at `in_window_not_executable`, and that gate runs before anything is written to the offer tape. |
| **LAX** | 166 (20:29:31Z-20:50:02Z) | **(d) zero-eligible-snapshot, after a normal eligible period** | Rows start at 20:29:31Z. That is 12 s after the 26 °C observation, which made rung 80-81 current, was first fetched at 20:29:19Z. Rows stop at 20:50:02.69Z. That matches **the last tick on which rung 80-81's ask sat inside the band (20:50:02Z, ask 0.09)**. From then on rung 80-81 was at 0.02-0.04, rung 78-79 was at 0.95-0.99, and no other LAX rung printed a single in-window tick. |

**Rejected on evidence:** (a) WS subscription starvation, (b) listing/instrument gap, and (c) a defect in per-station iteration.

The "stall" came from an assumption, not a fault. `DECISION_FUNNEL_2026-09-20.md` counted offer-tape rows, but the offer tape records only snapshots that pass the gates `ContinuousRungHoldStrategy._hunt_tick` runs first (`continuous_strategy.py:1180-1351`). The two gates that removed LAX/MDW are `not_executable` (`:1324-1335`) and `rung_not_current` (`:1345-1351`). They increment a process-lifetime counter that is logged only once, at `on_stop`. The tape cannot show them, and the 22:43Z snapshot was taken before any `on_stop`.

Mechanism and market condition are separate questions here:
- **Mechanism:** the executable-ask band gate. It is correct by design.
- **Condition:** both markets had repriced to near-certainty inside their windows. MDW had done so before its window opened, and LAX did so 50 minutes into its window.

One genuine code-level coverage gap turned up along the way. It is named under Follow-ups (F-1) and was not fixed.

## Evidence

### E1. Strategy diagnostics per station (node log; the counters the tape cannot see)

Source: `~/.local/share/breezy/logs/breezy-trade-20260920T165028Z.log`, written by the node process that ran from 2026-09-20 16:50:29Z to 2026-09-21 16:40:45Z. Each `ContinuousRungHoldStrategy` instance holds one station's six 09-20 rungs. It logs its snapshot in `on_stop` and then immediately unsubscribes its own instruments, and that unsubscribe line identifies the station:

```
2026-09-21T16:40:45.776581767Z ... diagnostics snapshot: {'in_window_not_executable': 3710, 'in_window_rung_not_current': 966}
2026-09-21T16:40:45.779312709Z ... UnsubscribeOrderBook(instrument_id=tc-temp-laxhigh-2026-09-20-lt76f...      -> LAX
2026-09-21T16:40:45.782866878Z ... diagnostics snapshot: {'in_window_not_executable': 826}
2026-09-21T16:40:45.782991512Z ... UnsubscribeOrderBook(instrument_id=tc-temp-mdwhigh-2026-09-20-lt69f...      -> MDW
2026-09-21T16:40:45.783543555Z ... diagnostics snapshot: {'in_window_not_executable': 4061, 'in_window_rung_not_current': 2747}   -> MIA
2026-09-21T16:40:45.784008584Z ... diagnostics snapshot: {'in_window_not_executable': 10005, 'in_window_rung_not_current': 6143}  -> SFO
```

MDW reached the hunt path 826 times in its window, and every one of those evaluations was refused as not executable. None got as far as the running-max, rung, or tape stages. There were no `open_intent_wait`, `rearm_wait`, `family_halt`, or `day_budget_exhausted` counts on 09-20.

Command:
```
sed -E 's/\x1b\[[0-9;]*m//g' ~/.local/share/breezy/logs/breezy-trade-20260920T165028Z.log \
  | grep -A2 -E "diagnostics snapshot" | grep -E "diagnostics snapshot|UnsubscribeOrderBook"
```

### E2. Subscriptions and listing were equal across stations (rejects (a) and (b))

- The node log's initial MARKET_DATA subscribe lines show **6 rungs per station per climate day** for all five cities. The same count, 6, applies to LAX, MDW, MIA, NYC and SFO on both 09-20 and 09-21.
- The strategy logged `ContinuousRungHoldStrategy subscribed ...` for all six 09-20 rungs of LAX (log lines 344-359) and of MDW (lines 370-385), at 16:50:34Z.
- The WS pool shards 10 slugs per connection. The log shows `opened shard-1; shards=2 slugs per shard=10` and later shards up to `shards=9`, so the shared 10-subscription cap is absorbed by sharding.
- Inside the 17:00Z-01:00Z window span, all 10 quote-tape gaps (`Quote tape gap #1..#10`) closed after about 5.0 s.
- LAX and MDW quote ticks are present in the ingested catalog throughout their windows (E3).
- The recorder journal shows the same listing count: `journalctl --user -u breezy-quote-tape.service` at 2026-09-20 21:00:42 logged `discovery cycle loaded 60 active market(s) ... discovery count before=60 after=60 resolved=0`.

Commands:
```
grep "sent MARKET_DATA subscribe" n0920.log | awk '$1<"2026-09-20T16:51"' | grep -oE "tc-temp-[a-z]+high-2026-09-2[01]" | sort | uniq -c
grep -oE "opened shard-[0-9]+; shards=[0-9]+" n0920.log | sort -u
grep -E "Quote tape gap #[0-9]+ (OPENED|CLOSED)" n0920.log | awk '$1>="2026-09-20T17:00" && $1<"2026-09-21T01:00"'
journalctl --user -u breezy-quote-tape.service --since "2026-09-20 16:00" --until "2026-09-21 02:00" | grep -iE "discovery (count|cycle loaded)"
```
(`n0920.log` is the ANSI-stripped copy of the node log above.)

### E3. In-window quote executability per rung (catalog `quote_tick`, deduped on `(ts_event, ask, size)`)

Source: `~/.local/share/breezy/catalog/quote_tape/polymarket_us/data/quote_tick/tc-temp-<stn>high-2026-09-20-*/`. The window is `[12,17)` LST: LAX/SFO 20:00Z-01:00Z, MDW 18:00Z-23:00Z, MIA 17:00Z-22:00Z. "executable" uses the strategy's own predicate, `0.05 < ask < 0.95 and size >= 1` (`config.py:234-236`).

| Station | Rung | In-window ticks | Executable | Dominant asks | Last in-window tick (bid, ask) |
|---|---|---|---|---|---|
| MDW | 69-70 | 189 | **0** | 0.99×128, 0.98×61 | 20:04:10Z (0.98, 0.99) |
| MDW | 71-72 | 119 | **0** | 0.02×85, 0.04×26, 0.03×8 | 22:16:58Z (0.01, 0.02) |
| MDW | 73-74 | 26 | **0** | 0.02×23, 0.03×3 | 18:35:57Z (0.01, 0.02) |
| MDW | lt69, 75-76, gte77 | 0 | 0 | — | — |
| LAX | 78-79 | 1041 | **0** | 0.97×371, 0.96×348, 0.95×151, 0.99×97 | 21:50:48Z (0.98, 0.99) |
| LAX | 80-81 | 1389 | 1040 (all in hour 12 LST) | 0.07×424, 0.06×386, 0.05×196 | 20:57:52Z (0.01, 0.02) |
| LAX | lt76, 76-77, 82-83, gte84 | 0 | 0 | — | — |
| SFO (control) | 65-66 / lt65 | 11134 / 11809 | 10502 / 7943, spread over all 5 hours | — | 00:57Z / 00:59Z |

In words: **MDW had no executable quote anywhere in its window**, and **LAX had executable quotes only on rung 80-81 and only in its first LST hour**. SFO, the station that "kept evaluating", had two rungs that stayed inside the band for the whole window.

LAX rung 80-81's crossings into and out of the band (`lax_trace.py`) show that the last executable tick coincides with the last tape row:
```
20:42:48 bid 0.01 ask 0.08 size 2000.0 executable
20:42:49 bid 0.01 ask 0.03 size 30.0 NOT executable
20:50:02 bid 0.01 ask 0.09 size 150.0 executable      <- last tape row ts_event 20:50:02.693Z
20:50:03 bid 0.01 ask 0.04 size 463.55 NOT executable
last 20:57:52 0.01 0.02 2455.03
```

### E4. Offer-tape rows (the "stall" as originally measured)

`offer_tape_2026-09-20.jsonl`: LAX 166 rows, all on rung 80-81 (83 `quote` + 83 `no_side_shadow`), running-max interval `[78, 80]` °F, non-exact, reason `observation_ambiguous`, first row 20:29:31Z, last row 20:50:02Z. MDW 0 rows. MIA 35,814 rows. SFO 27,228 rows.

### E5. Why LAX rows begin at 20:29:31Z (observation store)

`catalog/quote_tape/observations/observations_2026-09-20.jsonl`, KLAX running max inside 19:00Z-01:00Z:
```
new max 250 observed 19:30Z metar False first_fetched 19:49:19Z
new max 260 observed 20:15Z metar False first_fetched 20:29:19Z   -> interval [25.5,26.5] C = [78, 80] F closed -> rung 80-81 becomes current
```
The first LAX tape row follows the 26 °C fetch by 12 s. Before 20:29Z, LAX's executable rung (80-81) was not the current rung, which accounts for the 966 `rung_not_current` counts. After 20:50Z both current rungs were outside the band, which accounts for the 3,710 `not_executable` counts.

MDW's climate-day maximum in the store (06:00Z-06:00Z) is 21.0 °C (non-METAR, 11:15Z), with a METAR-only maximum of 20.6 °C. That is consistent with the market pricing 69-70 °F at 0.99.

*Discrepancy, stated rather than resolved:* `DECISION_FUNNEL_2026-09-20.md` gives MDW's final max as 220 tenths. This measurement gives 210 over the MDW climate day. The difference does not affect the verdict, because MDW refused at the `not_executable` gate, which runs before the running max is read.

### E6. The same pattern on the following days (corroboration)

| Day | Station | Tape rows | Diagnostics (node log, same method as E1) | Executable in-window YES ticks |
|---|---|---|---|---|
| 09-21 | MDW | 0 | `{'in_window_not_executable': 5120}` | 0 (rungs 65-66 at 0.99, 67-68 and gte71 at 0.02) |
| 09-21 | LAX | 210 (20:24-20:26Z) | `not_executable 3954, rung_not_current 3167, open_intent_wait 2` | 77-78: 1240, 79-80: 2004 |
| 09-22 | MDW | 8,506, including `taken` | `not_executable 4214, rung_not_current 3689` | 62-63: 4225, 64-65: 3655 |
| 09-22 | LAX | 0 | `not_executable 3673, rung_not_current 54, open_intent_wait 1` | 79-80: 53 only |
| 09-23 | all | MIA 348, others 0 | LAX `{'open_intent_wait': 100284}`, MDW `{'open_intent_wait': 27611}`, SFO `{'open_intent_wait': 115468}` | n/a: a **different** mechanism (open submit-intent WAIT after the 09-23 MIA take), not this item |

MDW produces rows when its market is executable (09-22) and none when it is not (09-20, 09-21). That relationship is the verdict. The station iteration is not broken.

## Follow-ups (named, NOT fixed here, no code changed)

- **F-1 (MEDIUM, coverage): NO-side hunting is gated on the YES leg's executability.**
  - Where: `src/breezy/strategy/current_rung_hold/continuous_strategy.py:1324-1335` returns `not_executable` when the **YES** ask is outside `(0.05, 0.95)`. That return comes before `evaluate_both_sides` (`:1368`) and `_evaluate_no_side_shadow` (`:1386`). The NO leg's own executable check, `no_ask = 1 - bid` at `decision.py:463-469`, therefore never runs on those ticks.
  - Measured (`nogap.py`, 09-20): LAX 78-79 had 1,041 in-window ticks with the YES ask out of band, and on **860** of them the implied NO ask (`1 - bid`) was inside the band. For SFO lt65 the figures are 3,360 of 3,553, and for MIA 88-89 they are 210 of 218.
  - Impact today: none, because AUD-01a's `no_side_calibration_unsafe` refuses the NO side and these LAX rows would also have been `observation_ambiguous`.
  - Why it still matters: it silently shrinks NO-side coverage once the NO gate clears, and it conflicts with the 2026-09-14 "NO-side hunting is a requirement" ruling.
  - Owner: a NO-side plan, not AUD-01b.
- **F-2 (LOW, observability): pre-tape refusals are only visible at process stop.**
  - Where: `not_executable` and `rung_not_current` go to `self.diagnostics`, a lifetime counter emitted once in `on_stop` (the "diagnostics snapshot" line), and never to the offer tape.
  - Effect: an intraday funnel, including the AUD-03 digest, reads "0 decisions" for a station whose market is closed, and that is how this item was opened.
  - Remedy options for a future plan: a per-station, per-hour periodic diagnostics line, or tape rows for pre-gate refusals.
- **F-3 (LOW, measurement): the 64 MiB offer-tape sidecar cap truncated 09-22.**
  - Where: `offer_tape.py:53` (`DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES`).
  - Measured: `offer_tape_2026-09-22.jsonl` is 67,108,527 bytes and 68,380 lines. The node logged at `2026-09-22T20:37:38.397Z`: `OfferTape: sidecar .../offer_tape_2026-09-22.jsonl reached its 67108864-byte cap; further rows are dropped from disk`. Every 09-22 row after 20:37:38Z is missing from disk.
  - Consequence: most of the LAX/SFO windows (20:00Z-01:00Z) and the end of the MDW window are lost, so 09-22 tape counts after that time are not evidence of anything.
  - The constant's own comment says "revisit once more live days are measured".

## Gaps against plan acceptance

- Plan §8 asks for the LAX/MDW cause with citations to rows actually inspected. That is **met** for 09-20 (E1-E5).
- **Per-evaluation attribution is not recoverable.** The 826 MDW / 3,710 LAX `not_executable` counts are lifetime totals from one log line each. The node records no per-tick record of which rung, or which trigger (`quote_tick`, `depth` or `on_data`), produced each count (F-2). The tick-level executability in E3 is reconstructed from the catalog under the strategy's own predicate, not read from the node's decision stream. The two agree: MDW had 0 executable ticks and 0 rows, and LAX's last executable tick matches its last row to the second.
- The `depth` trigger (OrderBookDepth10) was not decoded separately. Its best ask is the same top of book as the quote tick, and MDW showed zero eligible evaluations across all triggers (E1), so this does not change the verdict.
- The `^no` sibling instruments have no `quote_tick` partitions in the catalog. The F-1 implied-NO ask is therefore computed as `1 - YES bid`, which is the strategy's own definition (`decision.py:463`), rather than read from a NO book.

## Reproduction (scripts kept in the session scratchpad, all read-only)

Every Python run used `systemd-run --user --scope -q -p MemoryMax=4G /home/jon/breezy/.venv/bin/python <script> <day>`.

- `tape_counts.py`: per-station, per-hour `offer_tape_<day>.jsonl` rows, first/last `ts_event`, and `(station, source, reason)` counts (E4, E6).
- `quotes.py <day>`: for each station and rung, reads `quote_tick/*/**.parquet` (`ask_price` and friends are fixed-size 16-byte little-endian ints scaled by 1e16). It restricts to the `[12,17)` LST window, dedupes on `(ts_event, ask, size)`, and counts `0.05 < ask < 0.95 and size >= 1` (E3, E6).
- `lax_trace.py`: logs each crossing of LAX 78-79 / 80-81 into and out of the band between 20:00Z and 22:00Z (E3).
- `nogap.py <day>`: counts in-window ticks where the YES ask is out of band but `1 - bid` is in band (F-1).
- Observation max: iterate `observations_2026-09-20.jsonl`, dedupe on `(observed_at, is_metar)`, and track the running max with its first `fetched_at_ns` (E5).

## F-4 disposition (STALL_FOLLOWUPS_F1_F4_2026-09-24.md §F-4; added by the F-2/F-4 implementer, 2026-09-25)

**The gate is intended.** `is_intent_open()` (`trial_day_latch.py:643-662`) is the
account-wide R-7 singleton: "one order in flight at a time across the whole
account" (`MULTI_POSITION_PER_STATION_2026-09-14.md:100,113`). The 09-14
ruling lifted only one-position-per-station; the account-wide singleton
stands. The 09-23 row above (LAX 100,284 / MDW 27,611 / SFO 115,468
`open_intent_wait`) is this gate working as designed while a DIFFERENT
defect (an AMBIGUOUS order the resolver could not retire) kept the
singleton OPEN far longer than intended. That defect, not the gate, is
what this addendum measures.

**Measurement (read-only, `breezy-trade-20260923T165046Z.log` /
`breezy-trade-20260924T183812Z.log`, journalctl for `breezy-trade-supervisor`).**

- Intent opened 2026-09-23T17:22:07.912Z: `POLYMARKET_US` create-order for
  venue order `CP05MNWMAWP6` came back AMBIGUOUS ("create-order outcome is
  AMBIGUOUS; latch stays open and the booking is held").
- Every ~5 min from then on, the resolver's GET for `CP05MNWMAWP6` refused
  to map: `ExecutionReportMappingError: order status report field
  'leavesQuantity' does not equal 'quantity' minus 'cumQuantity'`, backoff
  climbing 1 → 285 consecutive failures.
- 2026-09-24T16:40:01.836Z: `open_intent_stale` CRITICAL fires (intent OPEN
  and AMBIGUOUS for >15 min — a per-check threshold, not the total age).
- 2026-09-24T16:40:12Z: the node is stopped (matches
  `node-refused-on-terminal-leaves-2026-09-24.md`: the next boot refused to
  launch on this same unresolved intent; A1 halt set 16:42Z).
- **Retired interval: ~23h18m** (17:22:07Z 09-23 → 16:40:12Z 09-24) — the
  intent was never retired by the resolver's own logic during that window;
  it was cleared out of band once the fix below landed (per
  `audit-backlog-execution-2026-09-24.md`: "intent retired, node
  hand-launched 20:15Z" on 09-24).

**Counterfactual, with mechanism (verified `git show --stat`, both SHAs
exist and merged on 09-24, AFTER the incident):**

- `df66327` ("a terminal non-fill order's leaves is zero") — its own commit
  message names root cause "the state-blind leaves check kept the intent
  OPEN (285 failures)", the SAME count measured above for `CP05MNWMAWP6`.
  The venue's GET for this order reports `ORDER_STATE_EXPIRED qty=1 cum=0
  leaves=0`; the pre-fix mapper treated `leaves != quantity - cumQuantity`
  (`0 != 1-0`) as an unresolvable contradiction rather than reading the
  terminal `EXPIRED` state's own `leaves=0` as authoritative. **Mechanism:**
  had `df66327` been live before 17:22:07Z, the very FIRST resolver GET
  (within the ~5 min poll interval) would have classified this order as a
  terminal non-fill and retired the intent — shortening the ~23h18m
  interval to roughly one poll cycle (single-digit minutes).
- `c3398bb` ("the AMBIGUOUS resolver loads a past-day instrument from the
  local catalog") fixes a SEPARATE failure mode: a node that only caches
  today's instruments loops forever on "instrument not in cache" when a
  leftover intent references YESTERDAY's instrument, blocking every
  subsequent launch. **Mechanism:** this is orthogonal to the 285
  mapping-error failures measured above (those failed on the leaves check,
  never reached an instrument-cache lookup); it would matter only if
  resolution had NOT completed same-day under `df66327` and the node had
  restarted into a new catalog day. Given `df66327` alone would have
  resolved this specific intent within the same UTC day, `c3398bb` was not
  the interval's binding constraint for this incident, but closes the
  otherwise-open next-day launch-deadlock path (L-48's "clearing path").

**L-48's clearing-path row for the intent latch:** OPEN → (resolver GET
maps a terminal state OR a confirmed fill) → `retire()` clears the
singleton. On 09-23/09-24 the GET never mapped (the state-blind leaves
check), so the latch had no clearing path available until `df66327`
shipped — exactly the "clearing path was blocked" reading the plan's F-4
disposition already names.
