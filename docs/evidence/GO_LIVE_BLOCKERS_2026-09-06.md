# Go-live blockers — merged analysis, 2026-09-06 19:15Z

**Question.** The node has been "LIVE" since 2026-09-04 with live n = 0. What,
concretely, stands between the current state and (a) the first live fill and
(b) a KILL-safe accumulation of live trials?

**Method.** Four read-only seams on Grok Build (execution spine, coverage and
the KILL clock, strategy admission and settlement, operations and operator
prerequisites), each with file:line / log / journal evidence; coordinator
verification of the two highest-impact claims directly against the code, the
registered spec and the live process cgroup and environment (names only).
HEAD `6285fb7`. Owner tags: **B** build, **O** operator.

## Ranked blockers

| ID | Owner | Sev | Blocker | Evidence | Unlock and observable | Size |
|---|---|---|---|---|---|---|
| GL-1 | B | CRIT | A sync IOC that does not fill is classified AMBIGUOUS, which DEGRADEs the node and leaves the submit intent OPEN. `classify_create_order_outcome` requires `state ∈ {CANCELED,REJECTED,EXPIRED}` and `cumQuantity == 0` (`submit_chain.py:680-701`); the documented `CreateOrderResponse` is only `{id, executions}` (create-order snapshot). | 09-05 20:19:49Z SFO IOC @0.28 → 20:19:54Z "outcome is AMBIGUOUS; latch stays open", `component_degraded` CRITICAL; venue `orders: []`; intent retired only at 01:08Z by operator. The 5.2 s matches `_MAX_BLOCK_TIME` (`submit_chain.py:100,292`). | Classify a documented empty-`executions` sync response as `KIND_ZERO_FILL`; log `body_kind`/`body_len` (the 09-05 binary logged neither). Observable: next IOC ends `KIND_ZERO_FILL` or `KIND_ACCEPT_FILL`, intent RETIRED without `OPERATOR_CLEARED`, no DEGRADED. | M |
| GL-2 | B | CRIT | A real fill with a sub-cent commission is refused and never booked. `parse_fill_report` → `_usd_money` → `_assert_representable` at `USD.precision` (`reports.py:86-88,414-419,865-868`); `fill_generation` swallows the error → `None` → AMBIGUOUS (`submit_chain.py:546-555,656-716`). Taker fee `0.06·p·(1−p)` is sub-cent at nearly every in-band ask (0.28 → 0.012096). | `codex_fill_chain_review_2026-09-05.md:30-34`; PROGRESS had it as [LOW] "commission 0.0111"; it is the first thing a real fill hits. | Persist the venue fee without refusing sub-cent values (cent-round with the raw value audited, or a higher-precision fee field). Observable: `DurableFillRecord` row in `exec_polymarket_us.sqlite` and `OrderFilled` on the first fill. | S |
| GL-3 | B | CRIT | `observation_ambiguous` consumes the station-day. `strategy.py:455-463` calls `self._latch.consume(...)` for every decision outcome; the registered rule says "no legal rung yet → skip, do not consume the station-day" (`grok_live_small_spec_rev2_2026-09-04.md:84`; PREREG v1 `:44`). Integer-°C 5-min observations span two rungs most of the time, so the day dies at the first in-window tick. | sqlite trial keys 09-05 MIA/LAX/MDW and 09-06 MIA/MDW = `observation_ambiguous`; alerts 09-06 17:00:00Z MIA and 18:00:00Z MDW (exact window-open minute). Verified by the coordinator in code and spec. | Refuse-without-consume on `observation_ambiguous` (record the refusal, leave the latch). Because the family is REGISTERED (PREREG v2 §13), obtain a strategy-lead ruling that this is conformance, not an amendment, before deploying; RED→GREEN on the latch test. Observable: no trial-latch row with that reason; a later unambiguous quote can Take. | S |
| GL-4 | B | HIGH | One AMBIGUOUS burns the rest of the day and every other station. The latch stays OPEN until an operator clears it (`client.py:56-58,1747-1758`); `arm` refuses while OPEN (`submit_intent.py:364-365`); `_has_durable_fill_record` is a stub returning False (`client.py:730-733`), so startup cannot self-retire. | 09-05: SFO AMBIGUOUS at 20:19Z, cleared `OPERATOR_CLEARED no-order-exists` at 01:08Z next day. Runbook §8 makes clearing manual. | Auto-retire a no-id AMBIGUOUS after a venue no-order probe (bounded retries, evidence written); keep operator clearing as the fallback. Observable: a later station can `arm` in the same process. | M |
| GL-5 | B | CRIT | Websocket reconnect storm makes afternoons uncovered. `_open_tape_gap` fires on every feed falling edge (`data.py:1685-1688,1812-1822`) at the 5 s watch interval; PREREG v2 §9 drops a station-day on ANY resolved-gap overlap with `[12:00,17:00)` LST (`structural_dead_stop.py:176-207`). | Recorder journal, instance `e3ede3ca` (09-05): 0 gaps 09:00–16:00Z, then 189 in the MIA window, 241 MDW, 281 Pacific; 1673 reconnects around the SFO submit; all four 09-05 station-days NOT covered (`score_live_trials.log:25-28`). Instance `1cdca371` (09-06) has 0 gaps 09:00–19:11Z. | Root-cause the reconnect storm (venue-side vs client backoff in `websocket.py`, host load, memory throttling) and make a 5 s blip not a full-window loss only if §9 is re-ruled (do not change §9 unilaterally). Observable: `journalctl -u breezy-quote-tape` shows 0 `gap #N OPENED` inside every station window; `covered_listed_station_days_*.json` count ≥ 1. | L |
| GL-6 | B | MED | The binding v2 tally never evaluates the structural-dead rule. `family_tally_v2.log`: "STRUCTURAL-DEAD UNAVAILABLE -- token 'refused' (required MATCH)": the 15:30Z timer runs while the node is down (launch 16:50Z), so the pin is dropped and the 09-06 v2 report has no structural-dead section. | `family-tally-v2-run.sh:86-94`; `breezy-pm-crh-v2-tally.timer:19`. | Make the MATCH token available at tally time (schedule the tally inside the node's window or derive MATCH without a live node, per the ruling). Observable: the v2 report carries "structural-dead stop … N covered-listed". | S |
| GL-7 | O | HIGH | Supervisor (pid 2231261) and node (pid 3079058) live in an uncapped coordinator scope `tmux-spawn-d35977dd-…` (MemoryMax=infinity, 9.3 GB current, 16.4 GB peak, 398 tasks) on a host with swap 6.9/8.2 GB used. Scope teardown or host pressure kills the node mid-afternoon; a recorder-covered afternoon with a dead node still counts toward the 15. | `/proc/2231261/cgroup`, `systemctl --user show` of that scope (coordinator-verified 09-06). Also carries SV-1: the running supervisor predates `c84317e` and will false-alarm NO_PERMIT every 17:05Z. | Operator relaunches the supervisor only (not today's node) from a host-lifetime shell that is not a `tmux-spawn-*` scope, with the seven values re-exported, outside 16:40–17:10Z (`hand-relaunch-mechanics`, L-26). Observable: `/proc/<sup>/cgroup` no longer `tmux-spawn-*`; next 17:05Z `self_check result=PASS`. | S |
| GL-8 | B | MED | Instrument set frozen at 16:50Z compose: `composition.py:116-150,220-237` reads the catalog once, `on_start` subscribes only `config.instrument_ids`, and the discovery reload is clamped to 21600 s (`data.py:250-264,1037-1044`). A HIGH rung listed after 16:50Z is never subscribed. | Today's log: 24 `subscribed` lines at start, none after. | Subscribe newly listed HIGH rungs intra-day (discovery → strategy subscription). Observable: a `subscribed` line after start for a slug absent at 16:50Z. | M |
| GL-9 | B | MED | The fill → `ScoredTrial` chain has never run on real data. `record_fill` sits on the accept-fill branch (`client.py:1636-1648`) that never executed; the trial store holds only `unresolved_takes.jsonl`; `score_live_trials` 09-06 "scored 0". | Store listing; `score_live_trials.log`; v2 tally n=0. | Drive a synthetic documented 200+fill body through the live submit chain and scorer in a test (RED first) so GL-1/GL-2 are proven together; then confirm on the first real fill. Observable: parquet row + tally n ≥ 1. | M |
| GL-10 | O/B | MED | Alerts are log-only: no `BREEZY_ALERT_WEBHOOK_URL` in the supervisor environment (names verified 09-06), so DEGRADED / AMBIGUOUS / self-check failures reach nobody until the next session. | `health.py:114,388-410`; env names of pid 2231261. | Operator supplies a sink; build verifies one delivered alert. Observable: a test alert arrives outside the log. | S |
| GL-11 | B | LOW | Recorder memory: kernel OOM 09-04 20:18Z (14.4 GB peak, inside the Pacific window) and SIGKILL 09-05 04:34Z at MemoryHigh. Both predate the frame-diagnostics deque fix; 09-06 rotation peak 914 MB. | Recorder journal. | Watch only: afternoon journals show no `OOM killer`/`status=9`; MemoryPeak stays well under 2 GB. | — |

## The clock

D0 = 2026-09-05, counter 0 (09-05 uncovered). If 09-06 onward stay covered
at four station-days per day with zero fills, the 15th covered-listed
station-day lands on the 09-09 or 09-10 tally. A zero-fill IOC or a retired
AMBIGUOUS is a take, not a trial, and does not defeat the stop (ruling
`codex_prereg_v2_rulings_2026-09-06.md`). GL-1, GL-2 and GL-3 therefore have
to land before the first clean covered cluster, or coverage has to stay
broken, which only delays.

## Verified NOT blockers (09-06)

- Execution client connected at 16:50:10Z, reconciliation succeeded,
  balances 97.91 USD (enough for one lot); live-trading permit issued
  16:50:09Z with a 10 h TTL; submit intent RETIRED, not OPEN.
- Operator caps and enablement are present in the live environment
  (`BREEZY_MAX_DAILY_BUDGET_USD`, `BREEZY_MAX_POSITION_COST_USD`,
  `BREEZY_TRADING_ENABLED` by name in pid 2231261's environ) and enforced per
  grant by `DailySpendLedger.authorize_order_cost` (`factories.py:777`,
  `client.py:1581`, `operator_controls.py:299-373`). The PROGRESS line
  "values not yet supplied" was stale.
- OP-SEQ positive control `CLOSED_YES_BOTH_VERBS` on 09-04 (GTC rest and
  cancel-all) — it did not exercise the IOC sync path (that is GL-1).
- Observation feed is live on the node: four `NwsObservationActor` READY at
  16:50Z, 300 s poll, 50 min staleness bound; the `observation_ambiguous`
  alerts prove observations reach the strategy.
- All 24 HIGH rungs for LAX/MDW/MIA/SFO subscribed at start; NYC excluded by
  config; qty 1 vs `minimumTradeQty` 0.01 fine; `allow_short` refused at
  construction; CRH does not call `RiskManager`.
- Recorder rotation is 09:00Z (02:00 PDT), not inside any window; the 00:15Z
  timer is ingest and does not restart the recorder; recorder cgroup
  MemoryHigh=2G/MemoryMax=3G in force, current 155 MB.
- Scoring and tally timers enabled (14:15Z, 14:30Z, 15:30Z); NWS finals land
  5–8 h before 14:15Z.
- G-16/G-17 gate the ROI programme, not the first fill. Kalshi S11 is off the
  Polymarket.us path.

## Hypotheses needing a measurement

- H1: the 09-05 body was `{id?, executions: []}` with no `state`; measure
  from the new `create-order AMBIGUOUS detail … body_kind=` line on the next
  submit.
- H2: the reconnect storm is afternoon-load related (09-05: 0 gaps before
  16:00Z, hundreds after); 09-06 contradicts so far. Measure the gap rate on
  `1cdca371` 16:00–00:00Z versus 09:00–16:00Z.
- H3: LAX/SFO consume as `observation_ambiguous` at 20:00Z tonight (MIA/MDW
  did). Measure the 20:00–20:05Z alerts and the latch keys.
- H4: venue `commissionNotionalCollected` is unrounded; measure the decimal
  places on the first 200+fill body.

## Operator-only questions

1. Relaunch the supervisor from a durable shell (GL-7) before 09-07 16:40Z?
2. Provide an alert sink (GL-10)?
3. Rule on GL-3 as conformance (strategy lead), so the fix can deploy on a
   registered family.
