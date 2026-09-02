# Grok design memo — M_B: the p_hold × ask edge measurement and its kill (2026-09-02)

Strategy/measurement design is routed to Grok by standing operator instruction. Verbatim Grok
output to the brief at the end of this file, read-only (`--permission-mode plan`,
`--disallowed-tools spawn_subagent,run_terminal_command`) against tree `268ca7d`.
Claude verification: the "09-02 discovery defect" Grok marks UNVERIFIED was investigated
and is a venue-side listing gap (no 2026-09-02 cohort was ever listed), not a recorder bug.

---


**Invariants.** Nautilus Trader is immutable. `allow_short` stays `False`. No safety/settlement/barrier/contract test is weakened. No operator-reserved control is assigned. No live-trading enablement, no NO-SEND change, no live orders. Analysis script only; Nautilus owns any later backtest.

Geometry (correct the brief): interiors are **closed 2°F** `[A, A+1]` (`gteAlt{A+1}f` settles A and A+1) — `Rung.contains` in `scripts/analysis/h4_preliminary_economic_read.py`. Not half-open 1°F. `m = R − A ∈ {0,1}` for interiors (`m=0` ≡ H4 headroom 1; `m=1` ≡ headroom 0). Open tails are a separate width class; never pool with interiors.

---

### 1. M_B

**Archive table** (run now; do not wait for tape). Reuse `build_running_max_days` + CLI finals (`scripts/analysis/pmr_climatology_study.py`; corpus `2021-01-01..2025-12-31`, complete 24h days only, dense stations only — NYC out, L-13). Proxy rung, same as PMR (historical listings unavailable — `docs/evidence/observation_lock_falsification_2026-08-31.md`):

| width | at `R` | hold iff CLI `tmax_f` |
|---|---|---|
| interior_2F, `m=0` | rung `[R, R+1]` | `∈ [R, R+1]` |
| interior_2F, `m=1` | rung `[R−1, R]` | `∈ [R−1, R]` |
| open_upper | `gte R` floor | `≥` floor |
| open_lower | skip in 12–17 LST | p_hold ≈ 0 by construction |

**Both exits count.** PMR’s primary “crossing = `M > upper_f`; `M < R` is neg-basis, never a crossing” (`docs/evidence/pmr_climatology_2026-09-01.md` §0) is **optimistic** for an interior YES. M_B `p_hold` is `P(CLI in rung)`, CLI-primary. `obs`-basis is a diagnostic only.

**Bins.** `(station, season ∈ {DJF,MAM,JJA,SON}, hour_lst ∈ {12..16}, width, m)`. No season pool (H4: MDW DJF `T*` fails a clock). Empty cell = `n/a`, never 0. **`n_min = 90`** per cell (G-01 `SAMPLE_FLOOR_PER_SITE`). Wilson 95% **lower** on hold, `z=1.959963984540054`, reuse `wilson_interval` (`scripts/analysis/archive_correction_probe.py`). Freeze this slice; tape days are holdout.

**Pre-filter from the existing table:** interior `m=1` is already CLI-REFUTED at every station/hour (`docs/strategies/archive/H4_headroom1_afternoon_lock.md`). Those cells are dead before any ask is joined. Only `m=0` interiors (and open-upper, separately) can reach the tape join.

**Tape join — do not attach `p_hold` to M_A winner rows.** Sibling snapshots: at each Depth10 instant in `[12:00, 17:00)` LST, `current = rung_containing(ladder, R(t))`, read **that** instrument’s ask/size. Coverage still from all-rung instants (`collect_window_instants`). L-8 preflight first.

Per lagged snapshot:

`edge = p_hold_lower(station, season, h, width, m) − ask − θ·ask·(1−ask)`

`θ = 0.06` (`src/breezy/adapters/polymarket_us/fees.py`; `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`). Missing/`n<90` cell → `edge` undefined, not 0. **K-depth:** `ask_sz ≥ 1.0` (`MIN_EXECUTABLE_SIZE`).

**Unit of inference = station-day, not snapshot.** MDW 9,472 rows are one climate day. Per station-day: the **first** lagged executable snapshot with current-rung ask ∈ `(0.05, 0.95)` (realistic entry — not afternoon min-ask shopping). Record its `edge`, ask, size, `(h,m,width)`. Pooled: fraction of afternoon-covered days with `edge > 0`, **station-stratified then conjunction** (H3 kill 6). Snapshot-weighted pools are forbidden.

**Sample to discriminate.** (i) archive: every cell that tape visits has `n≥90` or is `n/a`; (ii) tape: ≥ **15** afternoon-covered dense station-days (≥30 min Depth10 in window), same as K-A.

**Kill sentence.** Dead if, over ≥15 afternoon-covered station-days, **no** station-day’s first lagged current-rung snapshot has Wilson-lower `p_hold` strictly above `ask + 0.06·ask·(1−ask)` with size ≥ 1.0 — or if every tape-visited `(station,season,h,width,m)` cell is `n/a` / `m=1` / open-lower. Below 15: UNDERPOWERED, not dead.

---

### 2. Traps (encode)

**Survivorship.** Score the **current** rung at `t`, labelled later by whether CLI landed in *that* rung. Never the ex-post winner. A day where `R` jumps 93→94 contributes a loss on `[93,94]` and a new trial on `[94,95]`. M_A’s MDW/SFO qualifying cells are ineligible as M_B evidence until re-labelled.

**Latency.** We are not faster than an MM (L-9; H3: 300 s CLI poll). `ASSUMED_METAR_PUBLICATION_LAG_NS` is **UNKNOWN** (`docs/plans/intraday_observation_ingest_2026-09-01.md` §3). Public ASOS/METAR is the same information set. **Entry instant = first tape snapshot with `ts_event ≥ t_obs + lag`.** Ask at `t+lag`, never at `t` (that is the cancel race). Placeholder **10 min**; sensitivity `{5,10,15}`; K-B must hold at 10 **and** 15. `ts_init == ts_event` is unconstructible on the BL-24 record by design.

**Other.** Quiet winner book (MIA 09-01: coverage from other rungs, 0 winner depth) is a real no-trade, not a hole. Wilson independence is anti-conservative if errors cluster (`observation_lock_falsification` caveat). Do not mix 08-31 evening L-9 with this window.

---

### 3. Not a strategy. Next step (≤5 lines)

M_B surviving = at least one holdout station-day with `edge>0` at the lagged current-rung ask, in an archive cell with `n≥90`, station-stratified. **Only then** is BL-24 (`docs/plans/intraday_observation_ingest_2026-09-01.md`; `docs/core/PROGRESS.md`) worth building: `StationObservation` + `ts_init` fold so a Nautilus backtest can price that cell. A pass is not a GO to exec, live-small, or a strategy package. A kill leaves G-02 / K-programme as already written: recorder + offer-gate only.

---

### 4. Sample clock

Have **4** afternoon-covered days (09-01 LAX/MDW/MIA/SFO). Need **11** more. At ~3 usable dense/day: **~4 climate days** → ~2026-09-06 if 09-02 is lost, ~09-05 if recovered. **Archive `p_hold` does not wait** — ~1,800 complete days are already on disk. Only the tape-side kill waits for 15. 09-02 skip: **UNVERIFIED** in-repo (operator-stated).

**UNVERIFIED:** `m` on the 9,472 MDW rows (if `m=1`, archive already kills the 0.21); IEM vs `api.weather.gov` publication lag (BL-24 §3); 09-02 discovery defect; “3/day” going forward (09-01 was 4 covered, 3 with a winner ask).


---

## The brief Grok answered

# Design brief — M_A came back ALIVE-shaped; design the edge measurement and the kill

Read-only, from files only: NO shell and NO subagents in this run — do not attempt `run_terminal_command` or `spawn_subagent`. Repo root is the cwd. Under 150 lines.

## Invariants (binding — restate, never violate)
Nautilus Trader is immutable. `allow_short` stays `False` (long-only). Never weaken/delete a safety, settlement, barrier or contract test. Never assign a value to an operator-reserved control (max daily budget, max per position). Never touch live-trading enablement or the NO-SEND execution-egress firewall. No live orders are requested by this brief.

## What happened since your memo `docs/evidence/grok_no_edge_verdict_2026-09-02.md`
Your §2 measurement M_A was built (`scripts/analysis/ma_prelock_winner_ask_study.py`) and run. The first run said `n_afternoon = 0` — that was an artefact: the parquet catalog analyses query held two short sessions while 199,079 `OrderBookDepth10` rows for the 2026-09-01 afternoon sat unconverted in the recorder's Arrow stream directory. After native conversion, the re-run (`docs/evidence/ma_prelock_winner_ask_2026-09-02.md`, read it) gives **n_afternoon = 4** (one climate day, 09-01, four dense stations) and **9,588 qualifying snapshots** — winner ask ∈ (0.05, 0.95) while R(t) was inside the winner rung:

| station-day | winner | afternoon snapshots | qualifying | min ask | size@min | first ≥0.99 (LST) |
|---|---|---:|---:|---:|---:|---|
| MDW 09-01 | gte93lt94f | 14,293 | 9,472 | **0.21** | 25 | 15:56 |
| SFO 09-01 | gte70lt71f | 116 | 116 | 0.65 | 18 | – |
| LAX 09-01 | gte76lt77f | 1,781 | 0 | 0.83 | 77 | – (R(t) never in-rung while offered) |
| MIA 09-01 | gte89lt90f | 0 | 0 | – | – | – (quiet book, no depth updates all afternoon) |

So the pre-lock afternoon is NOT the 0.99/empty book L-9 measured post-lock: on 09-01 the eventual winner was offered mid-price, in size, while the running max already sat in its rung, on three of four stations. K-A did not fire (n=4 < 15). This is one climate day — it proves the window exists, not that it pays.

## What is still unknown, and why the ask alone is not an edge
"R(t) in-rung" does not mean the high has locked: an interior 1°F rung `[93,94)` at 13:00 with R(t)=93 can still be overrun by a later 94. The market's 0.21 may have been fair. The quantity that decides this is **P(CLI settles in rung r | station, local hour h, margin m = R(t) − floor(r), rung width, season)** — a climatology the repo can estimate from ~5 years of 5-minute ASOS for LAX/MDW/MIA/SFO (`~/.local/share/breezy/archive/settlement-alignment-cache`) joined to the NWS CLI archive, which is what `docs/evidence/h4_preliminary_economic_read_2026-09-01.md` §2 (`p_hold` after trigger) and `docs/strategies/archive/H3_intraday_running_max_lock.md` / `H4_headroom1_afternoon_lock.md` began; also relevant: the METAR↔CLI basis (H3 kill: 15–55% at h=0 by station) and `docs/evidence/observation_lock_falsification_2026-08-31.md`. Note ASOS 5-min obs are whole-°F on the H4 basis; CLI settles on the daily max from the same sensor but can differ (basis).

## What I need from you
1. **The edge measurement M_B, precisely.** Define `p_hold(station, h, m, width)` estimation from the archive (bins, minimum n per cell, Wilson bound to use, how to treat the METAR↔CLI basis so the estimate is not optimistic, how to handle open tails vs interiors), and the join with M_A's per-snapshot rows: per snapshot, `edge = p_hold_lower − ask − θ·ask·(1−ask)` with θ = 0.06 (`docs/evidence/` fee evidence), plus K-depth (size at the ask ≥ a minimum clip). Define the per-station-day and pooled statistics, the sample to discriminate (station-days AND archive cells), and **the kill sentence** (e.g. "dead if, over ≥15 afternoon-covered station-days, no snapshot cell has Wilson-lower p_hold above ask + fee with size ≥ N").
2. **Selection and timing traps** to encode: the winner is known ex post — M_A conditions on the eventual winner; M_B must instead evaluate EVERY rung R(t) is in at time t (the "current rung"), scored by whether it settles, so the estimate is not survivorship-biased. Say how. Also: when does the market learn R(t) (public ASOS/METAR latency vs our 5-min ingest — we are not faster than an MM), so what is the realistic entry instant and ask to use (the ask at t+lag, not at t).
3. **Do NOT design a strategy yet.** Only the measurement, its kill, and what result would justify the next step. State what that next step would be in ≤5 lines (I expect: BL-24 intraday ingest becomes worth building only if M_B survives).
4. Sample plan: the recorder now captures continuously; a discovery defect that skipped climate day 09-02 is being fixed; at ~3 usable dense stations/day, when is ≥15 afternoon-covered station-days reached, and does the archive-side estimate need to wait for that?

Cite files by path. Mark anything unverifiable UNVERIFIED. Be direct: if one climate day with a 0.21 ask on a rung that happened to hold is exactly the kind of survivor you warned about in your memo, say so first.
