# RULING — AUD-02 completion plan, step 5, Round 2 (2026-09-25)

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md` §3 (Rev 2.1).
Ruled by: prediction-market-reviewer (this doc) + trading-bot-architect (Round 1 ENDORSED_WITH_CHANGES; Round-2 edits below implement those changes).
Binding, not re-litigated: `forecast-edge-closed-pmus-rungs` (TERMINAL); `two-structural-gates-block-every-take`;
v4 family A1-HALTED (`e837511`/`AUD-02b_halt_deployment_2026-09-25.md`). AUD-18 is the sanctioned vehicle for any new edge.

## Step-5 qualifying-rate measurement (BLOCKER REMOVED)

Ran the worktree script (`/home/jon/breezy-wp7b@42848d5`), read-only, under the plan's exact wrapper:

    systemd-run --user --slice=breezy-studies.slice -p MemoryMax=4G --wait --collect -q \
      -p WorkingDirectory=/home/jon/breezy-wp7b -E PYTHONPATH=/home/jon/breezy-wp7b/src \
      /usr/bin/flock -w 1800 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
      /home/jon/breezy/.venv/bin/python /home/jon/breezy-wp7b/scripts/analysis/wp7b_market_as_forecaster.py \
      --since 2026-09-21 --output <scratch>/wp7b_since_2026-09-21_run.md

Exit 0. Output: `<scratch>/aud02s5/wp7b_since_2026-09-21_run.md`, sha256 `78330db886a807686081b30f008de2797aed8a6117fe2c401494ad13e31a70e6`.
Result: **no FORECAST ARCHIVE GAP recorded** (the MOS backfill closed it). **n=12 station-days admitted** since=2026-09-21, until=open. **Qualifying events: 0; qualifying station-days: 0 of 12 (rate 0.0000).**
95% CI on the rate, exact binomial (Clopper–Pearson; the script reports only the point count, so this is computed post-hoc on its own n/x, not a substitute statistic; no further clustering correction applies because n is already at the station-day level): **[0, 0.265]**.

**Pre-freeze figure was underpowered (n=8/64 = 0.125, `POST_FORECAST_PHASE_2026-09-20.md:283-284`) — noted, not relied on alone.** The fresh post-freeze figure (0/12) is *lower*, not higher. The CI's upper bound (0.265) is technically just above the 0.25 abandonment bar, so at n=12 the measurement cannot yet *statistically exclude* 0.25 — but the point estimate is zero and both the pre-freeze and post-freeze reads land on the same side of the bar. **Verdict: C1's abandonment-bar disposition is NOT reversed.** More data would only confirm or further lower the rate; nothing here creates a case to build C1.

## Dispositions

| WP | Disposition | Evidence | Trigger / forward-carrier |
|---|---|---|---|
| **B1** (permit-lapse detector) | **BUILD NOW** (changed from PARK) | Not yet built (no `permit_capability_valid`/`PERMIT_LAPSED` symbol). The daily-ceiling fix (`13e4849`, mid-day relaunch capped at first-boot expiry) bounds the WORST-CASE DURATION of an uncovered window but adds **no alerting** — a lapse inside the bound is still silent. B3's runbook already states the gap is "unalerted until B1 exists." Coordinator has dispatched B1 planning for peer review. | Build: RED-first per base plan's B1 row (`POST_FORECAST_PHASE_2026-09-20.md:46`), node-side Actor per resolution B-4. Plan to be peer-reviewed before implementation (planning gate). |
| **WP-T1** (offer-tape collapse, 53,624→6 rows) | **PARK** (unchanged; architect agreed) | Root cause still open (`FEE_SCHEDULE_PIN_2026-09-18.md:86`). **Confirmed: no `AUD-13b` id exists in this repo** (only AUD-13/13d, venue reconciliation, unrelated to tape-volume root cause). Not superseded by AUD-12b (fee-VALUE comparison, not tape-volume). | Trigger: next occasion the offer tape is cited as evidence for a live decision. Forward-carrier: AUD-18, only if it elects to use the offer tape as a data source. |
| **WP-Q1** (quote-tape gap root cause) | **CLOSE, softened** | `STATION_STALL_DIAGNOSIS_2026-09-24.md:51-52`: 10 quote-tape gaps closed in ~5.0s under the current sharding. Root cause (reconnect-driven, self-healing) stands. **Dropped:** the B-10 extrapolation that this also answers the NO-leg-degradation fear — that gap recovery was measured at the CURRENT, **YES-only** subscription count/shard layout; a future C1 NO-leg build could shard differently (more connections, different slugs/shard), and gap-recovery time under that layout is unmeasured. | If C1 is ever built: re-measure gap recovery under the new shard layout before relying on this figure again. |
| **C0** (WS subscription-cap probe) | **CLOSE** (unchanged) | Measured 10 subs/connection, shared MARKET_DATA+TRADE (`websocket.py:67,414,636-639`; `WS_CONCURRENT_CONNECTIONS_20260917T093016Z.probe.json`). | None required. |
| **C1** (NO-leg depth capture) | **PARK** (unchanged) | Still 0 `^no` dirs in `order_book_depths` (verified live). Abandonment bar (0.25/station-day) NOT met: pre-freeze 0.125 (underpowered, noted) AND fresh post-freeze 0/12 (CI [0,0.265]) both fail to justify the build; the fresh figure does not reverse the verdict. F-1's synthetic `NO_ask:=1-yes_bid` does not satisfy C1's "actually quoted NO ask" acceptance test. | Trigger: a qualifying rate meaningfully and repeatedly above 0.25/station-day via re-running this same script/flag as new climate days accrue. Sent to AUD-18 §6.3 NO-side triage input per C-6. |
| **C2** (frozen-region NO PnL readout) | **PARK** (unchanged) | Depends on C1 (n≥30 quoted-NO-ask observations); n=0. | Chained on C1's trigger. Terminal branch AUD-18 §6.6 KILL per C-7 if no independent edge estimate ever lands. Sent to AUD-18 §6.3. |

Criterion 5 (nothing protecting running parts is closed without a replacement): unaffected — node, capture, shadow valuation, KILL clock all continue under `family_halt` (submit-path-only veto).

## Tooling follow-up — DONE

- wp7b `--since`/`--until` + qualifying-rate report: **DONE**, `/home/jon/breezy-wp7b@42848d5`.
- IEM MOS NBS archive backfill, 2026-09-20..2026-09-26 (end exclusive), 483 rows/station: **DONE** (`~/.local/share/breezy/archive/iem-mos/`, `mos_nbs_backfill.json`, fetched=19/failed=0).
- **Remaining, NOT done by this ruling:** a *scheduled* recurring MOS refresh (so future climate days keep closing the archive gap automatically) does not yet exist. Owned by **AUD-18**, cross-referenced to its §6.3 NO-side triage input — the same input this ruling's C1/C2 dispositions feed.
