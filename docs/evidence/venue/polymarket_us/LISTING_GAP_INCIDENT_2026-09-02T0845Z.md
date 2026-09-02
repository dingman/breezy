# Venue listing gap — no 2026-09-02 weather cohort (measured 2026-09-02 08:35–08:45Z)

**Verdict: VENUE-SIDE. No data lost. No restart performed, none warranted.**

## What happened

Quote-tape capture rate fell from ~90 files/3min to ~77/hour, writing only
2026-09-01 instruments, while discovery logged
`market discovery returned zero configured-city weather markets this cycle;
refusing to treat this as [quiet]` on every cycle.

That refusal is the fail-closed guard behaving exactly as designed (L-8: a
0-row read is not a quiet market until proven). It was correct, and the thing
it refused to paper over was real: **the venue has not listed any 2026-09-02
weather markets.** They do not exist to record.

## Measurements (public gateway `/v1/markets`, read-only GETs, no credentials)

| Query | Result |
|---|---|
| `categories=climate, active=true, closed=false, archived=false` (Breezy's exact query) | **0 markets**, HTTP 200, 14-byte body |
| all categories, `active=true, closed=false` | **1** market venue-wide (a July sports market) |
| `categories=climate`, no active/closed filter | **3,653** markets |

The climate universe ends at slug-date **2026-09-01**. Tail cohort = 30 markets
(5 cities x 6 strikes), all `MARKET_STATUS_HALTED`, `closed=true`, `endDate`
05:00/06:00/08:00Z on 09-02. Direct slug lookups for four plausible
`...-2026-09-02-...` spellings returned **404**.

## The listing schedule, and the gap

Derived from `startDate` across the 08-23…09-01 cohorts: markets for day D are
created at **D−1 ~09:45Z**, drifting to ~10:30Z by the 09-01 cohort. The 09-02
cohort was therefore due **2026-09-01 ~10:30Z** and is ~22h overdue. **No
climate market anywhere carries a `startDate` on 2026-09-01** — the venue's
daily listing job did not run.

**There is precedent: 2026-08-28 is also absent** from an otherwise contiguous
08-23 → 09-01 sequence. Combined with the private backend returning 500/503 at
07:02Z, this reads as a venue-side incident rather than a permanent change.

## Breezy's discovery path is PROVEN HEALTHY — the worst case is ruled out

The dangerous hypothesis was a silently-dropped renamed or re-dated slug, which
would present identically to a genuine venue zero. It is refuted by
measurement: fed the 100 closed markets, `_weather_market_payloads`
(`provider.py:120-158`) **accepted 100/100** and resolved all five cities
(nyc 24, mia 22, mdw 18, lax 18, sfo 18). The slug grammar
`tc-temp-<city>high-<date>-<bound>` parses cleanly. The zero originates in the
venue's empty array, not in a rejection.

## The websocket reconnect loop — consequence, not cause; cosmetic

- **Onset 05:01:27Z**, one minute after the first cohort's 05:00:00Z `endDate`.
  (An earlier coordinator note gave 07:46:01Z; that was the sampling window's
  start, not the onset. Corrected here.)
- **Cause:** `ws_idle_timeout_secs = 60` (`config.py:277`). Hour 05Z shows
  exactly one close per minute — the idle timeout firing precisely. As the
  09-01 cohort expired city by city (NYC/MIA 05:00Z, MDW 06:00Z, LAX/SFO
  08:00Z) fewer instruments produced frames, the socket starved sooner, and the
  interval tightened to ~20s. **The venue closes us for silence; we do not
  close it.**
- **Not harmful:** 354 closes / 354 successful reconnects in 2h — 100% recovery
  on first attempt, retry budget never approached, `is_fatally_degraded` never
  set. The 71 gap records totalling 365s cover halted markets with nothing to
  emit. Discovery decayed 30 → 2 → 1 → 0 (last non-empty 08:18:03Z), which is
  the venue expiring the cohort, correctly observed.

## Coordinator's 07:40Z systemd actions: RULED OUT

`Reload requested … Reloading finished in 123 ms` at 07:39:41Z. Service shows
`NRestarts=0` and unbroken uptime since 04:38:48Z. The loop began 05:01:27Z —
**2h38m before** the reload. The daemon-reload neither restarted nor perturbed
the recorder.

## Why no restart

There are no markets to discover, so a restart fixes nothing, and it risks the
mid-message Arrow tail that makes the native read path return zero rows
silently. The discovery reload loop retries every 60s and continues after the
raise, so **when the venue lists the 09-02 cohort Breezy picks it up with no
intervention** — the `active=true, closed=false` query already demonstrated
this by discovering the 09-01 cohort at startup this morning.

## Consequences for strategy, not just ops

The venue's trading calendar **has holes** (08-28, and now 09-02). Any strategy
whose expected return assumes N trading days per period must treat listing days
as an observed quantity, not a constant. This also means an execution or
capital-deployment schedule keyed to "every day" will silently under-deploy.
Carry this into the portfolio-level ROI work rather than discovering it as an
unexplained shortfall.

## Open / filed, deliberately NOT fixed under this incident

1. **Latent silent drop (real hazard).** In `_weather_market_payloads` a market
   is skipped without comment when `parse_weather_slug` returns `None` AND the
   `question` field fails
   `^(?:Highest|Lowest) temperature in (?P<city>.+?) on `. Every other mismatch
   raises loudly. If the venue ever reworded the question, that `continue`
   would swallow it — and today proves the resulting zero is now a state we
   would attribute to the venue. That makes two very different conditions
   indistinguishable, which is precisely what today's guard exists to prevent.
2. **Log noise.** Demote the reconnect WARN to DEBUG when the active
   subscription set is empty; 354 lines / 2h for an expected overnight
   condition drowns real signal.
3. **Unresolved, not observable read-only:** why the venue skipped the 09-01
   listing run, and whether it shares a root cause with the 07:02Z private
   500/503s. Plausible, unproven.
4. The venue **ignores `orderDirection=desc`** — results always ascend by
   `endDate`. Discovery paginates so is unaffected, but the newest markets
   cannot be cheaply sampled.

## Watch

Re-probe the climate listing hourly; the cohort should appear ~09:45–10:30Z.
If nothing by ~12:00Z, escalate to venue support.

---

# UPDATE 09:20Z — auto-recovery CONFIRMED; venue RE-OPENED the expired 09-01 cohort

**The no-restart call is validated empirically.** With no intervention of any
kind, the recorder resumed on its own:

```
09:20:13 [INFO] discovery cycle loaded 5 active market(s), observed 0 resolved, discovered 5 total
09:20:13 [INFO] PolymarketUSInstrumentProvider: Loaded 30 instruments
09:20:13 [INFO] discovery cycle reload: subscribing tc-temp-mdwhigh-2026-09-01-gte91lt92f (new)
09:20:13 [INFO] discovery cycle reload: subscribed=('tc-temp-mdwhigh-2026-09-01-gte91lt92f',)
```

Recorder PID 3459201 unchanged, `NRestarts=0`, uptime unbroken since 04:38:48Z.
Nothing was restarted and nothing was lost.

## What actually came back is NOT the 09-02 cohort

The venue **re-opened the EXPIRED 2026-09-01 markets**. Measured transition:

| Time | Breezy's exact query | Cohort state |
|---|---|---|
| 08:35-08:45Z (triage) | 0 markets | 09-01 `MARKET_STATUS_HALTED`, `closed=true` |
| 08:39Z (coordinator) | 0 markets, 14-byte body | — |
| 09:06Z (coordinator) | 0 markets, 14-byte body | — |
| **09:20Z** | **5 markets** | 09-01 `MARKET_STATUS_OPEN`, `closed=false`, `tradable=true` |

`ep3SyncedAt`/`updatedAt` on the returned markets are 09:14:29-09:19:29Z, so the
flip happened inside that window. **There is still no 2026-09-01 `startDate`
cohort and still no 09-02 slug** — the missing listing run is NOT yet resolved.

## The strategically interesting part

Every re-opened market has an `endDate` that has ALREADY PASSED
(`2026-09-02T06:00:00Z` for MDW, `08:00:00Z` for SFO) and is nonetheless
`MARKET_STATUS_OPEN` with `tradable: true` on both sides. Example:
`tc-temp-mdwhigh-2026-09-01-gte91lt92f`, Yes at 0.0400; and
`tc-temp-mdwhigh-2026-09-01-gte93lt94f`, No at 0.6.

The observation window for "highest temperature in Chicago on September 1" is
physically CLOSED — the day's high is already determined — while the market
remains open pending the NWS Climatological Report that settles it. That is
precisely the post-observation / pre-settlement window the settlement-print-lock
work targets, and the recorder is now capturing it live. Treat this tape segment
as high-value: it is direct evidence about how the venue prices a determined but
unsettled outcome, which is exactly the regime any print-lock edge lives in.

**Do not infer an edge from this note.** It records that the window exists and
is being captured, nothing more. Whether it is tradable after fees, and whether
the quotes are real depth or a stale book nobody is maintaining, are open
questions for the archive gate to answer on the captured data.

## Still open

The 09-02 cohort remains unlisted and is now ~23h overdue. Keep watching; if
nothing appears by ~12:00Z, escalate to venue support. A venue that re-opens
expired markets before listing new ones is behaving oddly enough that the
"listing job did not run" reading should be held loosely.

---

# UPDATE 10:10Z — the 09-02 skip is CONFIRMED, and a SECOND, Breezy-side incident

## Part 1 — the listing gap resolves, but not as "delayed"

At ~09:45:30Z the venue listed a cohort — for **2026-09-03**, skipping 09-02
entirely. Measured `createdAt` on the new markets is `2026-09-02T09:45:30Z`,
which lands exactly inside the D-1 ~09:45-10:30Z schedule derived earlier. So
the venue's daily listing job is **working normally**; the only run that failed
was the single one on 09-01 that would have produced the 09-02 cohort.

**2026-09-02 is therefore a confirmed NO-MARKET day** — the third such gap after
2026-08-28 and (by the same mechanism) itself. No escalation to venue support is
warranted: nothing is broken venue-side now. The earlier note's advice to
escalate if nothing appeared by 12:00Z is superseded.

For the strategy work this is the reinforcement of the earlier point: the venue
calendar has holes, they are not announced, and a period's trading-day count is
an OBSERVED quantity.

## Part 2 — the new cohort exposed a Breezy defect that stopped capture dead

The moment the 09-03 cohort appeared, discovery began failing every 60s:

```
[ERROR] DataClient-POLYMARKET_US: Polymarket.us discovery reload cycle failed
(InstrumentDefinitionError: Polymarket.us payload is missing required field
'updatedAt'); the reload loop continues and will retry on the next scheduled pass.
```

Measured against the live gateway: **20/20 of the newly-listed markets carry
`createdAt` and NONE carries `updatedAt`.** The venue omits the field on a
market it has never modified since listing; it appears on first update. Breezy
required it, and because one unparseable market aborts the entire discovery
cycle, a single never-updated market blocked ALL of them. Capture went to zero.

**This invalidates the morning triage's prediction** that "Breezy picks it up
automatically with no intervention." It did not. That prediction rested on the
parser being "proven healthy, 100/100 accepted" — true of the sample, which
consisted entirely of already-updated markets, and false of the newly-listed
population. Recorded as L-17.

### Fix and rollout

`parsing.py` now falls back to `createdAt` for `ts_event` when `updatedAt` is
absent — semantically correct, since a market never updated was last changed
when it was created. Deliberately NOT a synthesised `0`/`now()`, which would
corrupt the tape rather than refuse it; `createdAt` stays required, so a payload
with neither still raises. Exactly one field widened.

Verified against the REAL live payload before rollout: 20/20 parse, `ts_event`
equals the parsed `createdAt`. Gate 5116 passed.

Rolled out by `systemctl --user restart` (SIGTERM, `KillSignal=15`,
`TimeoutStopSec=120`) — never SIGKILL, which leaves a mid-message Arrow tail
that makes the native read path return zero rows silently.

```
10:09:22 [old pid 3459201] discovery reload cycle failed (InstrumentDefinitionError)
10:09:41 [new pid  670812] discovery cycle loaded 30 active market(s)
10:09:41 [new pid  670812] Loaded 30 instruments
```

Post-restart: 0 errors, 30 instruments subscribed, **196 catalog files written
in the following 120s**, newest 4s old.

### Cost, stated plainly

Cohort created 09:45:30Z; capture restored 09:09:41Z+ (10:09:41Z). **~24 minutes
of a new cohort's opening tape is permanently lost** — the segment with the most
price discovery and the least competition. That is the real cost of treating a
sampled field as a required one.

### Follow-up filed, not fixed

One malformed market aborting the whole discovery cycle is a genuine amplifier
(1 bad market blocked 30 good ones). Isolating a single market's failure without
losing fail-closed semantics for genuinely corrupt payloads needs its own
design: partial-cycle success semantics, skip-vs-abort when a DIFFERENT required
field fails, and whether a skipped market is retried next cycle or flagged.
