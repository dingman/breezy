# Forecast-to-learning work breakdown — 2026-09-18 (r3 + coordinator amendments)

Plan of record for reaching the goal state: live forecast-conditioned orders AND an out-of-process learning loop that promotes revisions without a code change. Derived from docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md and docs/evidence/FORECAST_LEVERAGE_AUDIT_2026-09-18.md. Three review rounds (architect, prediction-market-reviewer, trading-bot-architect); review files in the session scratchpad. Status: awaiting operator approval of the main points.

## R2 blocking-item index (every item resolved)

| ID | Resolution |
|---|---|
| **F1** | **RESOLVED in WP-11b:** exact-files list gains `trade_supervisor.py:394` (family-agnostic readiness derived from `sending_family_id`, not `BREEZY_CONTINUOUS_RUNG_HOLD`), `default_ports:760` (`continuous_family_active=` that predicate), `CONTINUOUS_*_KEY` store constants keyed by family id (`trade_supervisor_core.py:108-109`), `breezy-trade-supervisor.service:109`; tenth RED test `test_supervisor_arming_reads_no_family_specific_env_name`. |
| **F2** | **RESOLVED in WP-13 + WP-11b L-12 + WP-28:** density table is an on-disk DATA artefact sha-pinned by the manifest via the `boundary_artefact_path` / `boundary_inputs_sha256` pattern (`family_manifest.py:175-184`). WP-11b same-commit L-12 widen of `_REQUIRED_KEYS` adds `density_artefact_path` / `density_artefact_sha256` next to `composition_kind`. WP-28 asserts fc_v1→fc_v2 changes **only** manifest + artefact files. |
| **F3** | **RESOLVED in WP-26 + D11 + §7 last row:** WP-26 concrete deliverable = engine **WRITES** `deploy/families/{new_family_id}.json` (`DRAFT_NOT_REGISTERED`) + density artefact + sha. Operator residual = DRAFT→REGISTERED flip, set `sending_family_id`, `systemctl --user enable --now breezy-family-tally@<id>.timer`. D11 and §7 last row restated; walk re-run. |
| **F4** | **RESOLVED in WP-11b:** `phase0_family_permits` (`composition.py:230`) **retired**. Two bools it takes are deleted; Phase-0-shadow behaviour folds into `phase1_sending_permit(*, sending_family_id, permit, phase0_shadow=True)`. |
| **F5** | **RESOLVED in WP-27:** 18:30Z promotion slot measured against the **live node** (or MemoryHigh cap + slot rule), not only vs mb-daily; live-node-protection response during 16:50–01:00Z = **stop the study, never the node**. |
| **F6** | **RESOLVED in WP-11b risk row:** one sentence — per-family `family_halted` is global-equivalent under cardinality-1 exclusivity. |
| **SEQ-1** | **RESOLVED in WP-11b + §3:** WP-11b parallel with 0b after WP-0a (same marker line), **off the WP-10 chain**. |
| **SEQ-2** | **RESOLVED in WP-34 + WP-17 + §3:** WP-34 (ingest-actor first-boot count) sits at WP-17, not post-arming with WP-20. |
| **SEQ-3** | **RESOLVED in WP-7:** WP-9 folded into WP-7’s output artefact (historical §4.5(1–4) on 0b would-takes). WP-9 SUPERSEDED. WP-18 still recomputes on shadow tape. |
| **NB-1** | **RESOLVED in WP-8:** criterion-(2) “not worse than champion” tolerance band pinned in the power table next to `δ_promote`. |
| **NB-2** | **RESOLVED in WP-0e:** ING-1 replace-vs-extend **choice recorded** before WP-17 may claim any station-day “covered”. |
| **NB-3** | **RESOLVED in D13 + §6 Q3:** conservative fallback if S refuses D13 = WP-12 wait-on-0b; A still reachable. |

All R1 items remain RESOLVED as in r2 (R1-1 completed by F1/F2; was PARTIAL in r2). Market reviewer rated r2 HIGH with no blocking issues; those items are unchanged.

---

## R1 blocking-item index (carried; every item resolved)

| ID | Resolution | WP |
|---|---|---|
| **R1-1** | Active-family registry: one identifier, cardinality-1, `deploy/families/` resolution, family-parameterised scorer/tally/systemd; arming a promoted revision = manifest/env, never a source edit. Files + RED tests named in WP-11b. **r3:** F1 (supervisor) + F2 (density artefact) close the remaining holes that made A(2) false. | WP-11b (supersedes r1 WP-11) |
| **R1-2** | KILL non-laundering clause verbatim in §B continuation and WP-26/WP-19. | WP-26, WP-19, §B |
| **R1-3** | Learning ledger + criterion (2) restricted to **admissible** fills (exclude `duplicate_fill`, `q≠1`, `fee_unreconciled` resolver fills), same as PREREG v3 §5. | WP-20, WP-26, WP-31 |
| **R1-4** | `MULTIPLICITY_RULE` verbatim as WP-7 **pre-registration deliverable** (before first cheap-screen run). | WP-7 |
| **R1-5** | Every r1 STOP replaced by a named continuation + owner (table in §1 and per-WP GATE). | all gated WPs |
| **R1-6** | WP-0 replaced wholesale with amendment §C; added WP-0d fee-schedule drift; added WP-0e ING-1. | WP-0a..0e |
| **R1-7** | Forecast-value differential test + L-42 real-writer fixture. | WP-16, WP-14 |
| **R1-8** | L-46 option (a) as a **build** WP; D6 removed from operator list. | WP-12c |
| **R1-9** | L-1 validations as explicit WP-12 sub-steps (catalog partition, Actor/msgbus, registry/engine) **before** `forecast_catalog.py` is written. | WP-12.0 |
| **R1-10** | Five missing WPs added. | WP-31, WP-32, WP-33, WP-34, WP-27 timetable |
| **R1-11** | WP-12 RED tests (never-rewrite same `ts_init` range; `delete_data_range` no-op); actor-push contract; NBM-direct-live / IEM-backfill statement. | WP-12 |

**Non-blocking absorbed:** §13.1 (b)(c)(d)(e) off critical path (kept as WP-22..25); §D sequencing kept + D13; promotion horizon restated from **~0.27 admissible fills/day measured**; criterion (2) would-take wording explicit; r3 destination `docs/plans/`.

---

## 1. Current state (five lines) and WP-0

1. **No forecast ingest, no forecast trades.** No NBM/NBS/MOS/TXN/GFS/NWS-forecast/Open-Meteo/IEM-PIL in production; only CLI climate days + station observations. `ForecastPoint` / `forecast_catalog` / NBM actor: symbol not found. `pm_us_crh_fc_v1` has no manifest (`deploy/families/` has `pm_us_crh_cont`, `pm_us_crh_v2`, `pm_us_crh_exit_v4`, `kalshi_crh_v1` only). Audit §1; `forecast_source.py:5-9`; `ladder_ev/config.py:163-168` (`mode='full'` raises; only `'degraded'` legal).
2. **Live family is observation-conditioned climatology:** `pm_us_crh_cont` REGISTERED (`deploy/families/pm_us_crh_cont.json`). Path: supervisor → `app/trade.py:159-267` → `phase1_family_permits` (`composition.py:247-281`, 2-tuple of booleans) → `ContinuousRungHoldStrategy`. Manifest path is a **hardcoded module constant** `_LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH` (`app/trade.py:74` definition, `:251` use) → `deploy/families/pm_us_crh_cont.json`. Hold probs from frozen archive table; qty=1 IOC; YES+NO. Audit §2. **This constant is why A(2) is unreachable without WP-11b.** **Additionally (F1):** supervisor readiness is family-hardcoded — `continuous_rung_hold_env_active()` (`trade_supervisor.py:394`) reads `BREEZY_CONTINUOUS_RUNG_HOLD` (wired `default_ports:760`; set `breezy-trade-supervisor.service:109`); store keys `CONTINUOUS_STARTUP_EVIDENCE_KEY` / `CONTINUOUS_FAMILY_HALT_KEY` (`trade_supervisor_core.py:108-109`; reader `:379-391`) are per-family constants (`"continuous_rung_hold/halt"`). Arming `pm_us_crh_fc_v1` by `sending_family_id` alone would leave `continuous_family_active()` False.
3. **Learning is record-and-judge only.** Nightly `score_live_trials` (14:15Z, `deploy/systemd/score-live-trials-run.sh` — already enumerates REGISTERED `polymarket_us` manifests) → parquet; `family_tally_v2` (17:25Z, `family-tally-v2-run.sh` already takes `$1` family id; **unit files** are per-family copies) → SURVIVE/KILL/CONTINUE. No probability/fee/window/size update from fills. Rev 5 §13 a–e, registry, promotion engine: none in `src/`. Audit §3.
4. **Trade record:** 7 orders, 6 fills, **admissible n=3**, admissible PnL **−0.82**; CONTINUE; first look n=10. Last send 2026-09-15. Measured rate **~0.27 admissible fills/day** (3 admissible / ~11 days 09-04..09-15). PROGRESS still says n=0 (stale vs 09-16 tally). Audit §4.
5. **Node observability is lying; child unreaped.** 17:05Z `FAIL_NODE_NOT_READY` since 09-15 is a **wrong subscribe marker** (`STRATEGY_SUBSCRIBED_MARKER = "CurrentRungHoldStrategy subscribed"` at `trade_supervisor_core.py:83`; live family logs `ContinuousRungHoldStrategy subscribed`). `self_check` (`:432-486`) maps `not strategy_subscribed` → `FAIL_NODE_NOT_READY` (`:475-476`). Because `readiness_observed` (`:367-374`) stays false, `next_due` never returns `MIDDAY_WATCH` (`:670-675`). `spawn_node` (`trade_supervisor.py:588-615`) returns `Popen`; `_launch` keeps only `proc.pid` (`:920-933`) — the `Popen` is discarded, so `waitpid` never runs. `process_is_alive` (`:478-485`) already treats state `Z` as dead, but nothing polls after 17:05 if MIDDAY_WATCH is gated off. 09-16 zero orders = WAIT states; 09-17 = KLAX `observation_unavailable` from boot + `FEE_SCHEDULE_MISMATCH_REFUSALS (1)` on MIA/MDW/SFO. Tally unit: `POLYMARKET_US_EXEC_STATE_DB` missing from `breezy-pm-crh-cont-tally.service:44-51` only (present on v2-tally `:44`). Wrapper still requires it for every REGISTERED polymarket_us family (`family-tally-v2-run.sh:173-213`).

**WP-0 is ops/hygiene, not a forecast feature. All five gate A(3). Forecast 0a/0b/Stage-1-build may proceed in parallel; no family may send, score-as-trusted, or look until WP-0a/0b PASS; A(3) additionally needs 0c/0d/0e.**

### GATE continuation convention (R1-5, binding on every WP below)

A gate has **PASS** and **CONTINUATION**. CONTINUATION names the next path that still reaches state A, with an owner. Escalation to a ruling is a continuation, not a STOP. The only act that is allowed to leave A unreached is an S ruling that the operator has seen the three §B branches (or the analogous named branches) all fail.

### WP-0a — Wrong subscribe marker + unreaped child (stage: ops)  **[R1-6 §C]**

| | |
|---|---|
| **Title** | Make self-check and MIDDAY_WATCH true for the live family; reap zombies |
| **Deliverables** | (i) `STRATEGY_SUBSCRIBED_MARKER` (`trade_supervisor_core.py:83`) accepts **both** `CurrentRungHoldStrategy subscribed` and `ContinuousRungHoldStrategy subscribed` (WP-11b later parameterises this by `composition_kind`). (ii) Un-gate MIDDAY_WATCH from the false `readiness_observed` that the wrong marker produced — `next_due` (`:637-677`) must enter `MIDDAY_WATCH` when the child is the live family. (iii) Reap via `waitpid`/`Popen.poll` — stop discarding the `Popen` at `trade_supervisor.py:920-933`; `spawn_node` (`:588-615`) already returns it. (iv) TDD: RED tests in `tests/unit/test_trade_supervisor.py` / `test_trade_supervisor_cont_self_check.py` — continuous-family log → PASS; zombie state `Z` (`:478-485`) → reap + relaunch path, not a stuck FAIL_NODE_NOT_READY. |
| **Owner** | B (TDD fix) + O (relaunch via the unit, L-26) |
| **Depends on** | Nothing |
| **GATE** | **PASS:** 17:05Z `self_check` PASS on a continuous-family node; MIDDAY_WATCH runs; a killed child is reaped (no `<defunct>`); flock held by tracked pid; permit issued+unexpired. **CONTINUATION:** if the marker fix is green but the child still dies (FATAL WS) → MIDDAY_WATCH relaunch budget (already in `decide_midday_relaunch`); if budget exhausts → alert (already CRITICAL) + O relaunch next window. Never “STOP sending as a programme.” Do not count a day with no live child as a trial (L-38). |
| **Size** | S |
| **Risks** | Relaunch mid-window with a live position; SIGKILL vs SIGTERM (`breezy-trade-supervisor.service` uncapped). L-26: coordinator-launched node dies with the session — use the unit. |
| **LESSONS** | L-23, L-26, L-30, L-38 |
| **Unblocks** | WP-0b; **WP-11b** (same marker line; registry env-migration of the live unit) |

### WP-0b — Tally unit env (`POLYMARKET_US_EXEC_STATE_DB`) (stage: ops)  **[R1-6 §C]**

| | |
|---|---|
| **Title** | Make `pm_us_crh_cont` nightly look runnable |
| **Deliverables** | `Environment=POLYMARKET_US_EXEC_STATE_DB=…` on `breezy-pm-crh-cont-tally.service` (mirror `breezy-pm-crh-v2-tally.service:44` and `breezy-score-live-trials.service`). Wrapper already requires it (`family-tally-v2-run.sh:213`). Cont unit comment `:44-49` (“not needed”) is **stale vs SD-1 09-16**. Re-run 09-17 score+tally once env present. WP-11b later replaces per-family units with a template; this line must still be in the template. |
| **Owner** | B (unit file) + O (re-run 09-17) |
| **Depends on** | WP-0a if scorer’s `node_store_path_check` needs a live node |
| **GATE** | **PASS:** 09-17 (and subsequent) `family_tally_v2_pm_us_crh_cont_*.md` exists; n/S_k match scored parquet. **CONTINUATION:** missing parquet → WP-0c (i); still-missing env after the unit edit → deployment defect, retry the unit drop, do not invent a skip. Sequential test is MISSING (L-38) until PASS. |
| **Size** | S |
| **Risks** | Re-scoring must not rewrite 09-16 rows; provenance sidecar required even at 0 rows. |
| **LESSONS** | L-38, L-20, L-42 |

### WP-0c — Scorer 09-17 parquet + PROGRESS n + L-45 (stage: ops/hygiene)  **[R1-6 §C]**

| | |
|---|---|
| **Title** | Learning-grade observability: scored ledger, honest n, coverage counts |
| **Deliverables** | (i) 09-17 `scored_trials_*.parquet` under `derived/scored_trials/pm_us_crh_cont/` or documented skip. (ii) `PROGRESS.md:32,88` n=0 → n=3 / PnL −0.82 (09-16 tally) — one-line correction. (iii) After any recorder/subscription change, **coverage count** of instrument dirs vs subscribed list (L-45), not “no ERROR lines.” |
| **Owner** | B/O |
| **Depends on** | WP-0b for (i) |
| **GATE** | **PASS:** nightly score+tally green; PROGRESS n matches latest tally; boot coverage count empty-diff on the last recorder boot. **CONTINUATION:** coverage non-empty-diff → WP-0e (ING-1) before trusting tape screens / §13(d). |
| **Size** | S |
| **LESSONS** | L-5, L-20, L-38, L-45, L-8 |

### WP-0d — Fee-schedule mismatch: investigate, then capture as data  **[R1-6]**

| | |
|---|---|
| **Title** | Venue fee vs `required_fee_coefficient` is DATA, not a reason to weaken the refusal |
| **Deliverables** | (i) **Read-only investigation:** 09-17 `FEE_SCHEDULE_MISMATCH_REFUSALS (1)` on MIA/MDW/SFO vs `required_fee_coefficient=0.06` (`ladder_ev/config.py:131`; CRH `config.py:226`; take rule `decision.py` fee θ·ask·(1−ask)). Never weaken the refusal. (ii) Fold the live fee coefficient into the **existing drift-capture pattern** (venue JSON keys → code frozensets via capture tests; last capture 09-13 per audit §3). A venue fee change becomes a capture-test RED → widen the frozenset in the **same commit** (L-12), then a config pin update as a **new family revision**, never an in-place edit under running `S_k` (L-34). |
| **Owner** | B (investigate + capture-test extend) + S if the venue theta is a real change that must retune BE (new revision, not a silent cfg edit) |
| **Depends on** | WP-0a (honest journal of the refusals) |
| **GATE** | **PASS:** investigation note cites venue theta vs pin; capture test RED on a drifted theta; refusal still fires on mismatch. **CONTINUATION:** if venue theta ≠ 0.06 → mint a new revision (new `family_id`/D0) with the new pin; do not patch `pm_us_crh_cont` under its running n=3. Forecast family inherits the capture-test, not a hardcoded 0.06 hope. |
| **Size** | S–M |
| **LESSONS** | L-12, L-34, L-21, L-38 |

### WP-0e — ING-1 disposition  **[R1-6, A(3)]**  **[NB-2]**

| | |
|---|---|
| **Title** | Close the Depth10 ingest collision that zeros coverage |
| **Deliverables** | PROGRESS ING-1 (CRIT, sized S): 15-min ingest writes a partial live-instance depth slice and refuses every later write as non-disjoint (exit 3), so in-window Depth10 stays < 30 min and coverage reads 0. **Named choice, recorded before any “covered” claim:** replace-vs-extend, written into the WP-0e evidence note (NB-2). Then fix the collision, re-run coverage. Blocks monitor marks, hypothetical-hold corpus, 0b tape completeness (§4.6), §13.1(d), and “covered station-days.” |
| **Owner** | B |
| **Depends on** | Independent of forecast WPs; **gates A(3) and WP-17 “covered”** |
| **GATE** | **PASS:** in-window Depth10 coverage > 0; collision gone; L-45 boot count empty-diff; **replace-vs-extend choice is on disk in the evidence note.** **CONTINUATION:** if replace-or-extend is blocked by catalog trap 1 (same-range rewrite silent skip, nautilus `parquet.py:378-380`) → corrections as **new records with later `ts_init`**, never delete-then-rewrite (`delete_data_range` no-ops for identifier-less custom types, trap 2). Do not declare shadow “covered” while this is open **or while the choice is unrecorded**. |
| **Size** | S (already in PROGRESS) |
| **LESSONS** | L-45, L-20, L-38, L-35 |

**WP-0 fail-closed for sending:** no live orders from any family until 0a+0b PASS. Forecast 0a/0b **and Stage 1 build** may still run. Stage 4 arming forbidden until WP-0a/0b PASS **and** 0c/0d/0e are either PASS or explicitly waived by S with A(3) marked incomplete.

---

## 2. Work packages WP-1..n

### Stage 0a — measurement only (ruling licenses this; no ingest/strategy code)

### WP-1 — FC-0a-1 IEM MOS reachability probe (stage 0a)

| | |
|---|---|
| **Title** | Run IEM MOS (NBS/GFS) reachability probe |
| **Deliverables** | Artefact dir `docs/evidence/iem_mos_reachability_probe_<ts>Z/` from `scripts/venue/iem_mos_reachability_probe.py` (`:1-10`, EVIDENCE ONLY — NEVER INGEST). Command (PROGRESS:54): `BREEZY_LIVE=1 BREEZY_USER_AGENT=… uv run python scripts/venue/iem_mos_reachability_probe.py --output-directory … --apply`. Transport stays under `scripts/` (L-46). Gate in probe: row counts, distinct runtime days, two-tier 60/300/3-year (`:64-67`), not HTTP 200. Plan §4.0; RED test `test_reachability_probe_reports_row_counts_not_http_status`. |
| **Owner** | O |
| **Depends on** | Ruling filed (done). Triple unlock. |
| **GATE** | **PASS** iff NBS reachable with row counts for **all four** stations 2021→now; GFS optional (§4.0, §9). **CONTINUATION (amendment §B, R1-5):** (i) NBM direct from NOMADS (WP-2 artefact) as the forecast source for the short stations — **owner B/O**; (ii) GFS MOS where NBS is short — **owner O**; (iii) reduce the station set to those that pass (a 2–3 station family is still state A) — **owner B** (manifest `stations`). **Only if (i)(ii)(iii) all fail → S ruling.** Incomplete years → not PASS, extend the probe (O), never skip to 0b. |
| **Unblocks** | WP-3, WP-4 / FC-1-RERUN, WP-5, WP-6 |
| **Size** | S |
| **Risks** | Coordinator probe scope today KMIA-only; 4-station overlap is **this** deliverable. Budget 56. L-46: never move transport into `src/breezy/ingest/`. |
| **LESSONS** | L-8, L-46, L-12, L-1 |

### WP-2 — FC-0a-3 NOMADS/NBM discovery probe (stage 0a)

| | |
|---|---|
| **Title** | Run NOMADS/NBM discovery probe (Seam A) |
| **Deliverables** | Artefact from `scripts/venue/nbm_nomads_discovery_probe.py` (`:1-11`, EVIDENCE ONLY). Triple unlock. Answers q1–q8 (`:52-61`): bulletin path, Last-Modified/ETag, body size, cycles/day with TXN, retention, station-block grammar, robots/rate, retrospective lag. Stations KLAX/KMDW/KMIA/KSFO (`:72`). `allowed_hosts={nomads.ncep.noaa.gov}`, budget 18 (`:37-40`). Plan §3.1, §4.1, §11 Seam B. **This artefact is §B(i) — the NBM-direct continuation.** |
| **Owner** | O |
| **Depends on** | Ruling. Independent of WP-1. |
| **GATE** | **PASS:** q1 path + q3 body size + q8 lag samples present. **CONTINUATION:** NBS bulletin unreachable → this WP **is** the §B(i) source; if NOMADS also unreachable → §B(ii) GFS (WP-1 GFS rows) then §B(iii) drop stations. Partial q’s → INSUFFICIENT for live ingest design, re-probe before Stage 1 `max_body_bytes` (plan §5 RE-VERIFY) — **owner O**, not a programme halt. |
| **Unblocks** | WP-7 PIT lag; Stage 1 transport URL/body/lag; §13.5 cycles/day; WP-12 (source chosen) |
| **Size** | S |
| **Risks** | Candidate URL shapes UNVERIFIED constants (`:4`). Do not ingest from this script. |
| **LESSONS** | L-1, L-17, L-46 |

### WP-3 — FC-0a-2 backfill CLI + real 1-min ASOS run (stage 0a)

| | |
|---|---|
| **Title** | Durable IEM 1-min cache populated (R(t) reconstruction) |
| **Deliverables** | Backfill CLI over existing `ArchiveCache` (`archive_cache.py:234`, `IEM_ASOS_1MIN_SOURCE:47`, `coverage.json` `_MANIFEST_NAME:49`). First **real** 1-min ASOS run for KMIA/KSFO/KMDW/KLAX, 2021→now, 1 req/s named pacer, process-then-discard per station-year (§3.6). Off-`/tmp`, `~/.local/share/breezy/archive/`, disjoint from settlement backup (`assert_cache_root_disjoint_from_backup:208-215`). Partial-write RED test (§5). Plan §3.6, §4.3; L-13 cadence. Cache **merged** (PROGRESS:55); CLI + real run are the follow-on. §13.1(a) reads this **same** cache. |
| **Owner** | B (CLI) then O (run) |
| **Depends on** | WP-1 (transport exercise). Cache module exists without the probe. |
| **GATE** | **PASS:** `coverage.json` lists four stations × years needed for 2021-01-01..2024-12-31 fit + 2025 holdout. **CONTINUATION:** missing station-years → rerun the CLI for those years (O); if IEM 1-min is short at a station → that station drops to §B(iii) (cannot fit R(t) there) — **owner B**. 0b fit blocked until PASS or the station set is reduced. |
| **Size** | S–M (run is wall-clock + 1 req/s) |
| **Risks** | L-13: do not mix 1-min and 5-min extrema without downsampling. 16G nightly cap, one heavy job (§4.11). |
| **LESSONS** | L-13, L-16, L-20, L-46 |

### WP-4 — FC-0a-4 Phase B / FC-1-RERUN (stage 0a)

| | |
|---|---|
| **Title** | Freeze `(icao, runtime, ftime) → climate_day` map |
| **Deliverables** | Phase A already: `scripts/analysis/forecast_climate_day_map.py` (`:1-10`, `:32-36` TXN period INFERRED). Phase B (PROGRESS:57; plan §3.3, §4.2): per-station CLI-truth alignment script, 3 fixtures **before 0b** (MIA bleed, SFO/LAX PST miss, DST), digest freeze (`FROZEN_TABLE_SHA256` is None until then), evidence doc. Confirm or refute P1/P2 (`:53-59`). v5 cycle split is a measurement (§4.3/§4.6), not a guess. |
| **Owner** | B |
| **Depends on** | **WP-1 artefact** (PROGRESS:57 BLOCKED) |
| **GATE** | **PASS:** three fixtures RED-then-green; map frozen. **CONTINUATION (R1-5):** TXN window ≠ climate day at a station → **per-station map**; that station **drops out** (§B iii) — **owner B**. Do not fit a wrong map. Do not halt the family for the passing stations. |
| **Size** | S |
| **Risks** | Silent v5 TXN semantic shift (§10). Wrong map labels every density cell. |
| **LESSONS** | L-1, L-3, L-44 (`forecast_climate_day_map.py:71-73` leg-invariant) |

### WP-5 — 0a gate close (stage 0a)

| | |
|---|---|
| **Title** | Single 0a PASS/FAIL on four-station NBS row counts, with §B already bound |
| **Deliverables** | RED test named in §4.0; evidence note citing WP-1 TSV row counts for KLAX/KMDW/KMIA/KSFO 2021→now. One gate, not two (§4.0). Records which §B branch is armed if not all four NBS-complete. |
| **Owner** | B (test) + O (artefact) |
| **Depends on** | WP-1, WP-2 (for §B i), WP-4 (map not required for raw row counts but required before 0b) |
| **GATE** | **PASS:** §4.0 four-station NBS, **or** a recorded §B branch with a non-empty station set. **CONTINUATION:** NBS short → §B(i)(ii)(iii) as WP-1 GATE; **only if all three fail → S ruling** (R1-5). Ruling:13 “Stage 1+ requires Stage 0b PASS” still binds **arming/registration**; D13 permits Stage 1 **build**. |
| **Size** | S |
| **LESSONS** | L-8, L-3 |

---

### Stage 0b — fit / holdout / PIT / cheap screen (no ingest/strategy code)

### WP-6 — 0b fit corpus + scripts (stage 0b)

| | |
|---|---|
| **Title** | Build 0b study scripts and run the fit/holdout |
| **Deliverables** | `forecast_conditional_model_study.py` (≤800 lines) and `forecast_tape_screen.py` (≤400) (§4.11). Fit: chosen source (NBS and/or NBM-direct and/or GFS per WP-5) ⨝ CLI truth, **2021-01-01..2024-12-31 fit, 2025 held out** (§4.3). `R(t)` = IEM 1-min/5-min from WP-3 cache (L-13). NBS = p_fc model when present; GFS = baseline/drift only **unless** §B(ii) promoted it to the model. Density key/coarsening **once**, jointly, in §7.5. Train-window-leak refuses (§4.11). Reuse `fit_error_model` `train_end_exclusive` guard (`calibration.py:8-23,60-103`) — **do not call from a strategy handler**. |
| **Owner** | B |
| **Depends on** | WP-5 0a PASS-or-§B, WP-3 cache, WP-4 frozen map |
| **GATE** | **PASS:** scripts deterministic-given-same-inputs; leak test RED. Fit artefact + 2025 holdout metrics written. **CONTINUATION (R1-5):** leak/non-repro → engineering fix + rerun (**owner B**); empty join → WP-5 source branch (§B i/ii/iii) (**owner B**). Do not screen a leaked or empty fit. |
| **Size** | M |
| **Risks** | `ladder_ev` parked/untested reshape later; 0b must not import strategy. 16G cap, one-shot wake (§4.11). |
| **LESSONS** | L-1, L-13, L-21, L-16 |

### WP-7 — 0b PIT + cheap screen + MULTIPLICITY_RULE + historical §4.5 artefact (stage 0b)  **[R1-4] [SEQ-3]**

| | |
|---|---|
| **Title** | Two-lag PIT + cheap mid-book screen under a **pre-declared** variant set; historical pre-Stage-4 computation is **this WP’s output artefact** (former WP-9) |
| **Deliverables** | **PRE-REGISTRATION (before the first cheap-screen run) — MULTIPLICITY_RULE, verbatim:** (i) enumerate the full variant space up front (windows × hour partitions × side pricing × station subset) as a **bounded pre-declared set**; never add variants ad hoc; (ii) Holm-Bonferroni (or a pre-declared FDR q) across the enumerated set on the cheap-screen **selection** decision; the per-cell bar (≥20 station-days, ≥50% positive, median ≥0.03) stays a **measurement gate**; (iii) pre-declared cap `K_variants`; exhausting it is a legitimate halt that **escalates to a ruling** (not a silent extra variant); (iv) every attempted variant’s table is logged; (v) **FIREWALL invariant:** variant search only on 2021–2025 fit/holdout; the confirmatory statistic (PREREG v6 `S_k`, pre-Stage-4) only on 2026 shadow+live data collected **after** the variant is frozen. Seed set **must** include: the two PRE-REGISTERED windows **09–12 and 12–17**; hours 10–11 pre-window per WIN-1; NO-side pricing; ask-screen variants (§B WP-7 branch). PIT: live NOMADS first-availability vs cycle runtime, ≥100 cycles/station, stratified by cycle hour, bootstrap CI on p95; pre-2026 `lag_era = max(observed strata)+6h` (§4.1). Trial unit = **one station-day**, first filled take, never per-hour rows; CIs cluster-robust block bootstrap by station-day. MAE/RMSE-by-lead (§4.6); tape completeness (incomplete days excluded — needs WP-0e); liftability qty=1 L0-fillable from Depth10; expected takes/station-day **both sides, all rungs**, plus NO `no_bid_side` rate (§4.10, §10). STOP/INSUFFICIENT-DATA **exit 0, never raise** (§4.11). **FOLDED WP-9 OUTPUT ARTEFACT (SEQ-3):** among would-take rows, station-day units, both sides: `StratumRow(side="yes"\|"no")` → `combine_station_day()` → `score_combined()` — **never** `score()` (raises on `side!="yes"`, `current_rung_hold_v2.py:150-169`). `build_stratum_v2` **twice**, YES-only and NO-only homogeneous subsets (E5; `:418-423` raises on mixed/`side!="yes"`). Report expected takes/day and `no_bid_side` rate. This artefact is the historical §4.5(1–4) computation; WP-18 recomputes the **same** four gates on the shadow tape (do not re-derive on a third corpus). |
| **Owner** | B (run) + prediction-market-reviewer (variant-set + multiplicity sign-off **before** first run); review of the §4.5 artefact: prediction-market + mle |
| **Depends on** | WP-6, WP-2 (live lag samples) |
| **GATE — 0b PASS** | **Cheap screen:** at least one **pre-declared** variant clears the bar “≥20 station-days, ≥50% margin>0, median≥0.03” in at least one reported hour (§9 / §4.4). Flat median≥0.03 is the **Stage-0 measurement gate only**; live uses `margin(h, n_cell, cfg)` (`scoring.py:56-62`). Holm-Bonferroni/FDR applied to the **selection** across the enumerated set. **INSUFFICIENT-DATA (extend, never a calibration verdict):** (i) two-lag PIT flips PASS/FAIL for a cell (§4.1, §9); (ii) any cell/hour/window never reaching n≥20 station-days (§4.5, §9). **Calibration thresholds (pre-declared, 2025 holdout):** `Brier_fc ≤ Brier_clim − δ` (INFERRED δ=0.01 — **set by WP-8 power table before PREREG v6**); reliability `|observed − predicted| ≤ ε` (INFERRED ε=0.05) per bucket on the **same** holdout. 2026 tape only TESTS these numbers (§4.5). **§4.5(1–4) on the historical artefact (gates Stage 4 / registration, never 0b / never Stage 1 build), verbatim:** (1) `score_combined` cluster-robust **Wilson-UPPER-of-realized < mean(BE_i)**, n≥150 (n≥60 only if claimed p≥0.9, realized≤0.75) → **KILL this variant**. (2) Either side’s `cell_dead` True (Wilson-UPPER of that side’s hit rate < that side’s mean(BE_i), n≥60) → Stage 4 refused. (3) 150 station-days, real forecast source, **zero honest takes** → operational KILL of this variant. (4) Table-valid calibration kill vs WP-8 thresholds. **INSUFFICIENT-DATA** (n<20 cell): extend shadow, never a verdict. **CONTINUATION (R1-5, amendment §B):** cheap screen fail on the first variant → run the **next pre-declared variant**, log its table (**owner B**); `K_variants` exhausted → **S ruling** (this is the one halt that may end the thesis, and only after the enumerated set is complete). INSUFFICIENT-DATA → extend corpus/shadow (**owner B**), not a PASS. Firewall breach (confirmatory peek at 2021–2025 after freeze) → discard the confirmatory statistic, freeze a new variant, restart confirmatory on post-freeze 2026 data (**owner B**). Fail (1–4) → **re-enter WP-7** at the next pre-declared variant; **arming refused only while every variant fails** (**owner B**). Do not weaken the gate. |
| **Size** | M |
| **Risks** | Forecast already in the price (L-7) — §4.8 cycle-age-vs-margin is the test. Empty YES bid side → high `no_bid_side` (§10). Ad-hoc extra windows after seeing results = multiplicity laundering — refused by (i). |
| **LESSONS** | L-7, L-8, L-21, L-35, L-13, L-40, L-41, L-44 |

### WP-8 — 0b power table (stage 0b → PREREG inputs)  **[NB-1]**

| | |
|---|---|
| **Title** | Replace INFERRED loop/calibration constants with 0b-measured values |
| **Deliverables** | Power table setting `δ`, `ε`, `δ_promote`, **`tol_not_worse`** (criterion-(2) tolerance band vs strict inequality — NB-1), `N_promote`, `K`, `M`, `T` **before PREREG v6 registration** (§4.5, §13.3). `tol_not_worse` sits **next to** `δ_promote`: “not worse than champion on the same days” means challenger CI-lower ≥ champion CI-lower − `tol_not_worse` (0 = strict inequality). None is an operator value; none a third knob. |
| **Owner** | B + S (if a constant cannot be identified from 0b, ruling — not operator guess) |
| **Depends on** | WP-7 (frozen variant) |
| **GATE** | **PASS:** every INFERRED constant in §4.5/§13.3 has a measured or ruling-pinned value, **including `tol_not_worse`.** **CONTINUATION (R1-5):** unidentified constant → **S ruling** that pins it; bounded retry = mint the power table from the frozen variant + the ruling. Cannot register PREREG v6 until PASS. Not a programme halt. |
| **Size** | S |
| **LESSONS** | L-21, operator-caps rule (PROGRESS:17-24), L-39 (never name reserved env vars) |

### WP-9 — SUPERSEDED. Folded into WP-7’s output artefact.  **[SEQ-3]**

r2 WP-9 duplicated WP-18’s §4.5(1–4) computation on a different corpus (0b would-takes vs shadow tape). The historical computation is now a **named output artefact of WP-7**. WP-18 remains the confirmatory recompute on shadow tape. Do not implement a separate WP-9.

---

### Stage 3.0 / 1 / 2 / 3 — build (Stage 1 **build** ∥ 0b per D13; registration/arming wait on 0b PASS)

### WP-10 — Stage 3.0 `ladder_ev` `mode='forecast'` (stage 3.0)

| | |
|---|---|
| **Title** | Extend `ladder_ev` for forecast mode without touching CRH files |
| **Deliverables** (plan §7.1–§7.7, E1–E2, E6): | `config.py` — `mode='forecast'` third branch; `'full'` stays hard-refuse (`config.py:163-166`); `window_start_hour_lst`/`window_end_hour_lst`; `forecast_staleness_bound_ns`; `publication_lag_ns`; additive `forecast_corpus_pin` vs the **manifest-pinned** `density_artefact_sha256` (F2; **no** `FORECAST_CORPUS_SHA256` src constant — WP-13). `density_table.py` — **new** `ForecastDensityKey`/`ForecastDensityTable`/alphabet `{below,contains,above1,above2,above3+}`; `DensityCell.p_upper`; `_wilson_upper`; existing 6-rung `RUNG_IDS`/`DensityKey` **byte-unmodified**. Runtime **loads** the table from the artefact path; it does not embed table bytes in `src/`. `decision.py` — `ExclusionInputs.side`; family call site replaces X8 (§7.4); window reads cfg (E1). `scoring.py` — `OpportunityRow.side`; NO EV via `edge_after_costs(intent_long_yes=True, model_p=1−p_upper)` (E2 — **never** `intent_long_yes=(side=="yes")`). `depth_adapter.py` — **new** `bid_levels_from_book` fail-closed. `forecast_state.py` NEW (`value_at(now_ns)`). `allow_short` stays False (`config.py:159-162`). **Zero edits** to `continuous_strategy.py`/`tick_eval.py`/CRH `decision.py`/`archive_table.py` (§1). |
| **Owner** | B; python-reviewer |
| **Depends on** | None for **build** (D13). Merge-to-arm waits on WP-7 0b PASS. |
| **GATE** | **PASS:** existing `tests/strategy/ladder_ev/*` green (DEGRADED regression); new unit tests for forecast-mode key/NO EV/`no_bid_side`. **CONTINUATION:** fail → do not merge; fix and rerun (**owner B**). Do not start ingest against a broken density shape. |
| **Size** | M |
| **Risks** | Parked package (§10). E2 vs leftover §7.6 `intent_long_yes=(side=="yes")` — **E2 wins**. |
| **LESSONS** | L-1 (Nautilus `StrategyConfig` extend, not a new engine), L-2, L-12, L-44 |

### WP-11 — SUPERSEDED. Do not implement the three-boolean design. See WP-11b.  **[R1-1]**

r1 WP-11 would have added `forecast_ladder_edge: bool` beside `current_rung_hold` / `continuous_rung_hold`, extended `phase1_family_permits` to a 3-tuple, and still left `_LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH` as a source constant. A promoted `pm_us_crh_fc_v2` would have required a source edit. **That contradicts A(2).** Skip this WP.

### WP-11b — Active-family registry (cardinality-1)  **[R1-1] [F1] [F2 L-12] [F4] [F6] [SEQ-1] — load-bearing for A(2)**

| | |
|---|---|
| **Title** | One sending-family identifier resolved against `deploy/families/`; promotion is a manifest/env act; supervisor arming is family-agnostic |
| **Exact files that change** | **`src/breezy/app/trade.py`:** delete `_LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH` (`:74` definition, `:251` use). `run()` (`:159-267`) no longer early-returns when both legacy flags off (`:175-182`); no longer unpacks a 2-tuple (`:206-211`). Boot resolves `settings.sending_family_id` → `deploy/families/{id}.json` → `load_family_manifest` (`family_manifest.py:126-213`). Dispatch to the builder named by the manifest’s `composition_kind`. **`src/breezy/strategy/current_rung_hold/composition.py:247-281`:** replace `phase1_family_permits(*, current_rung_hold, continuous_rung_hold, permit, phase0_shadow) -> tuple[Permit, Permit]` with **one** `phase1_sending_permit(*, sending_family_id: str, permit, phase0_shadow: bool = False) -> OrderSubmissionPermit \| None`. Cardinality-1 is **structural** (one slot), not an N-boolean mutex. `phase0_shadow` 2-family CRH coexistence remains a **named build-side hatch** for the v2/v3 transition only; it cannot name two **sending** ids. **F4 — RETIRE `phase0_family_permits` (`composition.py:230-244`):** it takes the two booleans this WP deletes. Fold its Phase-0-shadow behaviour (v2 may hold the permit; v3 never does) into `phase1_sending_permit(..., phase0_shadow=True)`. Tests that called `phase0_family_permits` retarget. **`src/breezy/runtime/settings.py`:** replace `current_rung_hold: bool` / `continuous_rung_hold: bool` (`BreezyTradeSettings:761-768`) and parsers (`:319-324`, load `:811-847`) with **one** `sending_family_id: str \| None` (build-side flag, **not** a reserved cap — do not name the daily-budget / per-position controls, L-39). `rung_hold_family = sending_family_id is not None`. `orders_enabled` (`:834-847`) requires live observations **and** a sending family id. Unknown id / missing file / `DRAFT_NOT_REGISTERED` without `allow_draft` → `SettingsError` (mirrors `UnregisteredFamilyManifestError:97-98`, `UnpinnedBoundaryArtefactError:101-102,180-184`). **`src/breezy/persistence/family_manifest.py:60-213`:** L-12 **widen** `_REQUIRED_KEYS` (`:62-73`) **in this same commit** with (i) `composition_kind: Literal["current_rung_hold","continuous_rung_hold","forecast_ladder"]` (and `_STRING_FIELDS`) **and (ii) `density_artefact_path` / `density_artefact_sha256`** (F2; same pin shape as `boundary_artefact_path` / `boundary_inputs_sha256` at `:175-184` — 64 lowercase hex; all-zero refused unless `allow_draft`). Exact-set refusal for unknown keys **unchanged**. Existing CRH manifests updated in the **same commit**: they receive `composition_kind` plus a committed **sentinel** density artefact (`deploy/families/artefacts/not_applicable_density.json` with a real sha, **not** `_UNPINNED_SHA256`) so REGISTERED load still works. Forecast family pins the real table at WP-13/WP-15. **`tests/contract/test_rung_hold_families_mutual_exclusion_contract.py`:** **AMENDED / WIDENED, never weakened** — assert (a) two sending ids cannot be expressed (type/settings), (b) each `composition_kind` alone boots, (c) DRAFT cannot send, (d) `phase0_shadow` cannot mint two sending permits, (e) **no two manifests can be active** in one boot. **`src/breezy/runtime/trade_supervisor_core.py:83`:** subscribe marker becomes family-parameterised (WP-0a’s both-CRH prefixes is the stopgap; this WP maps `composition_kind` → class-name marker, including `ForecastLadderStrategy subscribed`). **F1 — supervisor arming, exact files:** **`src/breezy/runtime/trade_supervisor.py:394`** — replace `continuous_rung_hold_env_active()` (`True` iff `BREEZY_CONTINUOUS_RUNG_HOLD=="1"`, via `CONTINUOUS_RUNG_HOLD_VAR` at `settings.py:109`) with a **family-agnostic** predicate derived from `sending_family_id` (True iff a sending id is set). Arming `pm_us_crh_fc_v1` must **not** leave `continuous_family_active()` False — otherwise the self-check family block never runs (`SupervisorPorts.continuous_family_active` default-False at `:737-740`; `_do_self_check` only enters the continuous-family checks when that port is True). **`trade_supervisor.py:760` (`default_ports`):** `continuous_family_active=` that predicate (today `=continuous_rung_hold_env_active`). **`CONTINUOUS_*_KEY` store constants keyed by family id:** `CONTINUOUS_STARTUP_EVIDENCE_KEY` / `CONTINUOUS_FAMILY_HALT_KEY` (`trade_supervisor_core.py:108-109`, duplicated from `trial_day_latch.py:280,315` because runtime must not import strategy) — halt is today the family-hardcoded `"continuous_rung_hold/halt"`; both keys become a function of `sending_family_id`. Reader `read_continuous_family_store_state` (`trade_supervisor.py:379-391`) takes the sending family id. Strategy-side `FAMILY_HALT_KEY` (`trial_day_latch.py:280`) widened the same way (same-commit L-12; layers contract still forbids runtime importing strategy — pin the two literals against each other in the existing self-check test). **`deploy/systemd/breezy-trade-supervisor.service:109`:** migrate `Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1` → `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_cont` (name matches the settings parser). Subsequent promotions change **only** that id + the new manifest. **`deploy/systemd` tally:** replace per-family tally units (`breezy-pm-crh-cont-tally.service`, `breezy-pm-crh-v2-tally.service`) with **one instantiated template** `breezy-family-tally@.service` / `.timer`, `ExecStart=…/family-tally-v2-run.sh %i`. Wrapper is **already** family-parameterised (`family-tally-v2-run.sh:1-8,38`, `$1` validated against `deploy/families/*.json`). Template **must** carry `Environment=POLYMARKET_US_EXEC_STATE_DB=…` (do not repeat WP-0b’s miss). `score-live-trials-run.sh:13-27,48-53,77+` already enumerates every REGISTERED `polymarket_us` manifest — keep that; do **not** add per-family scorer copies. Enable `breezy-family-tally@pm_us_crh_fc_v1.timer` at WP-15/WP-30 without a new unit file. |
| **RED tests (must fail before the impl)** | (1) `test_sending_family_id_is_cardinality_one` — two ids in env → `SettingsError`. (2) `test_unknown_sending_family_id_refused`. (3) `test_draft_manifest_cannot_send_without_allow_draft`. (4) `test_boot_loads_manifest_from_registry_dir_not_module_constant` — grep/AST: `_LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH` gone; `load_family_manifest(Path("deploy/families")/f"{id}.json")`. (5) `test_promoted_revision_requires_no_src_edit` — a fixture `pm_us_crh_fc_v2.json` with `composition_kind=forecast_ladder` boots as sender with **zero** `src/` diff vs v1 (only manifest + density artefact + env). (6) Contract: `test_no_two_manifests_can_be_active` (widened exclusivity). (7) `test_each_composition_kind_boots_alone`. (8) `test_phase0_shadow_cannot_issue_two_sending_permits`. (9) Template unit: `test_family_tally_template_passes_family_id_as_percent_i` (no per-family ExecStart literals for fc_v*). **(10) F1:** `test_supervisor_arming_reads_no_family_specific_env_name` — AST/grep: supervisor arming path contains **no** `BREEZY_CONTINUOUS_RUNG_HOLD` / `CONTINUOUS_RUNG_HOLD_VAR`; readiness is derived from `sending_family_id`; a fixture sending id `pm_us_crh_fc_v1` makes `continuous_family_active()` True and the self-check block run. |
| **Owner** | B; python-reviewer + **security-reviewer sign-off** (permit/intent + exclusivity contract) |
| **Depends on** | **WP-0a** (same marker line; live-unit env migration). **Parallel with 0b. Off the WP-10 chain (SEQ-1).** Registry shape (id + `composition_kind` + density keys + CRH kinds) does **not** wait on `mode='forecast'`. The `forecast_ladder` branch refuses to boot until WP-14. |
| **GATE** | **PASS:** all ten RED→GREEN; contract stricter than today; live unit migrated (`service:109`); `src/` contains **no** sending-family path constant **and no family-specific supervisor env name**; `phase0_family_permits` gone. **CONTINUATION:** fail → do not merge (safety). Bounded retry = fix the registry, never fall back to a third boolean. |
| **Size** | M |
| **Risks** | Shared day-budget is account-wide by design (§7.8). Env migration of the live node is an O act in the same change-set as the code — a half-migrated node composes nothing. `allow_short=False`; NO-SEND untouched; two caps unnamed (L-39). **F6:** per-family `family_halted` is **global-equivalent under cardinality-1 exclusivity** — with one sending family, a halt of that family is a halt of the node’s only sender. |
| **LESSONS** | L-12, L-22, L-43, L-3, L-39 |

**Arming a promoted revision after WP-11b:** operator sets `sending_family_id` to the new REGISTERED `family_id` (D11) and enables `breezy-family-tally@<id>.timer`. **Never a source edit.** Supervisor self-check follows the new id (F1). Density table travels as the artefact named in the manifest (F2). That is A(2).

### WP-12.0 — L-1 null-hypothesis notes (before any new module)  **[R1-9]**

Record these verdicts in the WP-12 commit message / module docstring **before** writing `forecast_catalog.py`. Citing installed 1.231.0 (skill `nautilus-trader-patterns`, verified):

| Question | Verdict | Installed evidence | Consequence |
|---|---|---|---|
| Does `ParquetDataCatalog.write_data` / `register_arrow` already give `(station, climate_day)` partitioning? | **NATIVE — insufficient.** Partitioning is attribute-driven (`parquet.py:320-336`): `Instrument` → `bar_type` → `instrument_id` → **else flat** `data/custom_<snake_name>/`. Trap 21: custom type without `instrument_id` **cannot** separate two stations in one catalog root. | skill traps 1, 2, 21 | Smallest extension: **one `ParquetDataCatalog` root per station** (native workaround) **or** an `instrument_id` field populated per-station. Do **not** invent a second parquet writer. Climate-day is a **query filter** on `ts_event`/`valid_*`, not a native partition key. |
| Live delivery of `ForecastPoint` to the strategy? | **NATIVE — sufficient** for the bus: `Actor.publish_data(DataType, Data)` + `Strategy.subscribe_data`. | `actor.pyx` publish/subscribe; observations already do this | Hot path is **actor-push → in-memory `ForecastState`**, never `catalog.query` (R1-11). Catalog is the durable archive / backtest source. |
| Champion/challenger registry + promotion engine? | **GENUINELY ABSENT** in Nautilus. | searched: no artefact registry, no promotion | BUILD out-of-process (WP-20, WP-26), reuse `FamilyManifest` exact-set **shape**, distinct schema. |
| NBM HTTP client / forecast product? | **GENUINELY ABSENT.** HttpTransport + Actor timers **NATIVE** (pattern `nws_observation_actor.py`). | ingest/http.py:522-546 | Smallest extension = custom `Data` + `NbmForecastTransport(HttpTransport)` + per-cycle Actor. |

### WP-12 — Stage 1 ForecastPoint + NBM/IEM ingest + catalog (stage 1)  **[R1-8, R1-9, R1-11]**

**May be BUILT in parallel with 0b (D13).** Arming/registration still require 0b PASS. **NBM direct is the live primary. IEM MOS (~40 h lag, whole °F) is backfill/fallback only** (R1-11). **If S refuses D13:** this WP waits on 0b PASS (conservative fallback); A still reachable.

| | |
|---|---|
| **Title** | Production forecast ingest (Nautilus-native custom data) |
| **Deliverables** (§5, §7.9): `domain/forecast_point.py` — `ForecastPoint(Data)` + `register_arrow` **once** at module scope, pattern `station_observation.py:4-11,73,255-261`. Schema §3.5: `station, model("NBM_NBS"|"GFS_MOS"), variable("TXN"), cycle_runtime_ns, valid_start_ns, valid_end_ns, value_f: float\|None (-99/999→None), available_at_ns`. Vintage: `available_at_ns = cycle_runtime_ns + measured_publication_lag_ns` (§3.2), never `ts_init`. `ingest/nbm_forecast_data_type.py` factory empty metadata (`iem_observations.py:36-45`). `ingest/nbm_forecast_transport.py` `NbmForecastTransport(HttpTransport)` (`ingest/http.py:522-546`), `allowed_hosts={"nomads.ncep.noaa.gov"}`. `ingest/nbm_forecast_actor.py` per-cycle timer Actor (`nws_observation_actor.py:109,172-178` — no loop ⇒ no network). `ladder_ev/forecast_catalog.py` writer+reader: **per-station catalog roots** (L-1 table above), `^`/`: ` separators, disjoint catalog root, read-back RED incl. `~`. `ladder_ev/forecast_composition.py` `build_live_forecast_actors`. In-node actor (not a study systemd); L-16 timer-swallow test. `find_execution_egress_modules()` RED. Parser raise-on-drift RED. Widen `tests/unit/test_weather_data_type_barrier.py` (L-12). **IEM fallback:** `ingest/iem_mos_fallback_transport.py`, `allowed_hosts={"mesonet.agron.iastate.edu"}`, named pacer ≥1s RED. **Never** `ProbeTransport`, never `SETTLEMENT_HOSTS`. |
| **WP-12c — L-46 option (a), same commit  [R1-8]** | Widen `tests/unit/test_archive_import_contract.py::test_settlement_transport_hosts_stay_nws_only_and_src_never_names_iem_host` in the **SAME commit** (L-12). **Re-scope the assertion to settlement modules** (the mutant the docstring names: “moving IEM retrieval into `src/breezy`” was protecting **settlement** hosts, not banning every IEM use). Restate the docstring: settlement transports stay NWS-only; forecast fallback is a **named, paced, distinct** `allowed_hosts` in `ingest/iem_mos_fallback_transport.py`. **Never disguise the host** (no `".".join`, no noqa-to-hide). D6 removed — this is not an operator choice. |
| **Actor-push contract (R1-11, pin into §7.1/§7.2)** | The decider consumes `ForecastPoint` via **actor push on the msgbus into an in-memory `ForecastState`** (never a catalog read in the hot path). RED: publishing a point updates `ForecastState.value_at`; with the actor absent, `forecast_unavailable` and **no take**. |
| **Owner** | B; python-reviewer + security-reviewer (egress) |
| **Depends on** | WP-12.0 notes written; WP-10 merged for `ForecastState`; WP-2 for `max_body_bytes`; WP-4 map; WP-5 chosen source. **Not** on 0b PASS for **build** (D13). |
| **GATE** | **PASS:** round-trip catalog; PIT guard; sentinel parse; v5/DST fixtures; staleness-never-silent; L-16; pacer ≥1s; zero-shared-state; IEM host contract widened not relaxed; actor-push contract; **R1-11 RED tests (below)** all green. **CONTINUATION (R1-5):** NBM live path down → IEM fallback transport is a **REQUIRED deliverable of this WP**, not a later nice-to-have; family records `forecast_unavailable` only while **both** transports fail, and WP-32 alerts. Do not ship a live primary with no fallback. |
| **Size** | M |
| **RED tests required (R1-11)** | (1) `test_same_ts_init_range_rewrite_is_refused_or_skipped_loudly` — never express a correction as a rewrite of the same `ts_init` range (Nautilus trap 1, `parquet.py:378-380` silent skip). Corrections = new records, later `ts_init`. (2) `test_delete_data_range_is_a_documented_noop_for_identifierless_forecast_point` — `delete_data_range` does not delete our rows (trap 2, `parquet.py:1386-1406`); the test **asserts the no-op** and forbids a “delete then rewrite” repair path. (3) actor-push contract above. (4) NBM-primary / IEM-fallback: live actor uses NBM host; IEM path is not the live timer’s primary URL. |
| **Risks** | `ForecastSource` protocol (`forecast_source.py:103-117`) is a **pull seam with no production source** — do not wire strategies to fabricate `expected_high_f` from `NwsClimateDay.tmax_f` (`:14-20`). Live path is `ForecastPoint` → actor-push → `ForecastState.value_at`. |
| **LESSONS** | L-1, L-12, L-16, L-17, L-20, L-46, L-45 |

### WP-13 — Stage 2 calibration freeze (stage 2)  **[F2]**

| | |
|---|---|
| **Title** | Promote 0b table UNCHANGED as an on-disk DATA artefact; freeze at registration via manifest pin |
| **Deliverables** (§6, §7.5, F2): generated forecast-mode table is **not** in `archive_table.py` posture and is **not** a `FORECAST_CORPUS_SHA256` config constant. It is an on-disk DATA artefact, named and sha-pinned by the family manifest using the existing boundary-artefact pattern (`family_manifest.py:175-184`: 64 lowercase hex; all-zero → `UnpinnedBoundaryArtefactError` unless `allow_draft`). Keys (already in `_REQUIRED_KEYS` from the WP-11b L-12 widen): `density_artefact_path`, `density_artefact_sha256`, sitting next to `composition_kind`. `CORPUS_SHA256`+`STUDY_GIT_SHA` live **inside the artefact bytes / sidecar**, not as src constants. Nightly job = §4.5 **drift/calibration monitor only**, never inline refit (refit = new revision + new artefact, §13.3). Tests: table-generation determinism; pin-mismatch refuses construction (mirror `:180-184`); drift-monitor synthetic above/below thresholds. |
| **Owner** | B; prediction-market + python-reviewer |
| **Depends on** | WP-12 schema fixed, WP-6/7/8 artefacts (0b PASS for the **table contents**; schema can exist earlier), **WP-11b** (density keys in the exact-set) |
| **GATE** | **PASS:** artefact written; `density_artefact_sha256` pinned on the DRAFT fc_v1 manifest; construction refuses pin mismatch. **CONTINUATION (R1-5):** pin mismatch / non-repro → engineering fix + rerun (**owner B**); cannot register until PASS. Champion breach of this monitor later → REJECTED, shadow-only on last-good, **new revision + new artefact** (§13.3) — not a halt of the programme; **not a `src/` edit**. |
| **Size** | S |
| **LESSONS** | L-21, L-34, L-12 |

### WP-14 — Stage 3 strategy + composition (stage 3)

| | |
|---|---|
| **Title** | `ForecastLadderStrategy` + composition + YES/NO submit |
| **Deliverables** (§7.2–§7.4, §7.10, E7): `forecast_strategy.py`, `forecast_composition.py`. Per-rung per-side scan; `r_relation` derived not keyed; COUNTER reasons `rung_physically_dead`/`forecast_unavailable`/`forecast_stale`/`no_bid_side` (not closed `Refuse.reason`). YES: listed instrument, `OrderSide.BUY` IOC qty=1. NO: `sibling_instrument_id` + `wire_price_for_leg("no", …)` at **submit only** (`leg_prices.py:56-96`); EV from inverted YES bids (E2). `station_day_admission` Σq≤1 joint; `TrialDayLatch.consume_if_absent` with `forecast_ladder_edge/trial/`. **RE-VERIFY** `_maybe_submit` line range before build (§1.2, §12). `lint-imports`: `ladder_ev.*` never imports `continuous_strategy`; ingest never imports runtime/strategy. Backtest subclass must not import `continuous_backtest_only` (E7). Hold-to-settlement; exit UNARMED (§1.4). qty=1 only. **L-42 (R1-7):** every test of a store-reading gate (latch, admission, `ForecastState`) **writes the fixture through the real catalog writer / actor**, not a hand-built `ForecastState`. |
| **Owner** | B; prediction-market + python-reviewer |
| **Depends on** | WP-13 table frozen (for the live artefact), WP-11b permits, WP-12 catalog/actors |
| **GATE** | **PASS:** WP-16 integration test green. **CONTINUATION:** fail → no registration, no shadow deploy; fix and rerun (**owner B**). |
| **Size** | M–L |
| **Risks** | Pre-existing `tests/integration/test_forecast_edge_backtest.py` is **unrelated** `ForecastHighEdgeBuyer` — reconcile, do not collide (E7, §10). |
| **LESSONS** | L-1, L-9, L-44, L-42, L-2 |

### WP-16 — §7.13 reach-the-goal integration test (stage 3.9)  **[R1-7]**

| | |
|---|---|
| **Title** | RED-first proof the family can take the thesis trades **and** that forecast value moves the take set |
| **Deliverables** | `tests/integration/test_forecast_ladder_family_backtest.py` (E7). Asserts (i)–(vi) §7.13: one NO take (inverted-bid, BUY on `^no`); one YES on `r_relation=above` (control with unmodified `is_legal_cell` **fails** this); `no_bid_side` on empty bid; both fills → one `CombinedDraw`; `score()` and mixed `build_stratum_v2` raise; CRH Decision stream byte-identical with forecast strategy absent; live-contention/cardinality-1 exclusivity (WP-11b, not a 3-bool test). `allow_open_positions`/`allow_idle_strategies` as separate flags. Confirm `SyntheticBinaryTape` one-sided book or extend fixture (E7). **R1-7 differential:** identical tape, two `ForecastPoint` fixtures one density-bucket apart → **different take set / `model_p`**; forecast absent → `forecast_unavailable`, **no take**. Points are published through the **real actor/catalog writer** (L-42), then consumed via `ForecastState`. |
| **Owner** | B; python-reviewer **sign-off mandatory** (§11) |
| **Depends on** | WP-14; written RED **before** strategy files exist (§7.13) — same change-set, RED first |
| **GATE** | **PASS:** all six §7.13 asserts + differential + L-42 writer path green on integration branch (L-43). **CONTINUATION:** fail → goal state not reached; do not register; fix (**owner B**). |
| **Size** | S |
| **LESSONS** | L-3, L-24, L-43, L-44, L-42 |

### WP-29 — Var(S) boundary artefact (stage 3, blocking registration)

| | |
|---|---|
| **Title** | H0 Monte-Carlo of this family’s mixed-side CombinedDraw vs pinned boundary |
| **Deliverables** | Seeded validation: `Var(S_terminal)≈1`; one-sided crossing ≤ α+slack (L-40, L-41). Either reuse `deploy/families/gs_boundary_pm_us_crh_v2.json` (`boundary_inputs_sha256=471fd8a7…c150e0c` in `pm_us_crh_cont.json:6`) **or** mint a new artefact. |
| **Owner** | B; prediction-market-reviewer |
| **Depends on** | WP-14 statistic frozen |
| **GATE** | **PASS:** at qty≡1. **CONTINUATION (R1-5):** fail → **mint a new artefact** (bounded retry, **owner B**) or **S ruling** if the statistic itself is misspecified. Never silently pin a wrong boundary. qty>1 is R-11 / MP-B, out of this family’s qty=1 scope. |
| **Size** | S–M |
| **LESSONS** | L-40, L-41 |

### WP-15 — PREREG v6 registration for `pm_us_crh_fc_v1` (stage 3)

| | |
|---|---|
| **Title** | Register the forecast family before first fill |
| **Deliverables** | New spec (no v6 file exists; **template** = `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md` §3 stop rule + §7.12 table). Manifest `deploy/families/pm_us_crh_fc_v1.json`: `family_id=pm_us_crh_fc_v1`, `composition_kind=forecast_ladder` (WP-11b), `density_artefact_path` + `density_artefact_sha256` (WP-13), `trial_id_prefix=forecast_ladder_edge/trial/`, stations = WP-5 surviving set, `d0_climate_day` **set at registration, never retroactive**, `status=DRAFT_NOT_REGISTERED` until register (`family_manifest.py:60-84,170-184`). Decision core `ladder_ev mode='forecast'`. Statistic: `combine_station_day`/`score_combined`; per-side `build_stratum_v2` pre-Stage-4; own 15-day KILL clock (§9) starting once ladder-scan **and** NO-path are live. Reuse v3 sequential: `S_k`, `I_max=40`, looks every 10 to 160, LD-OBF α=0.025/side, truncation D0+165 or `total_pnl≤−60`. **Var(S) consistency check** on the WP-29 artefact **before** pin (`boundary_inputs_sha256` blocking, R5-8). Secondary offer-tape endpoint PRE-REGISTERED as **learning** statistic, never feeding `S_k` (§9). Looks never peeked. **Admissible-fill definition** copied from PREREG v3 §5 into v6 (R1-3). |
| **Owner** | S (register) + B (manifest + boundary + density artefact) |
| **Depends on** | WP-8 constants, WP-14, WP-16, WP-29, WP-7 0b PASS **and WP-7 historical §4.5 artefact**, WP-18 for **arming** (registration may proceed DRAFT; live REGISTERED waits on pre-Stage-4) |
| **GATE** | **PASS:** `load_family_manifest` without `allow_draft`; unpinned sha raises `UnpinnedBoundaryArtefactError` (`family_manifest.py:101-102,180-184`) for **both** `boundary_inputs_sha256` and `density_artefact_sha256`. **CONTINUATION (R1-5):** unpinned / Var(S) fail → rerun WP-29, mint a new boundary artefact, obtain S ruling if needed (**owner B then S**). No fills, no arming until PASS. New family, n resets to 0. |
| **Size** | S–M |
| **Risks** | Reusing v2 boundary if Var(S) differs (§10) — then **new** artefact, not a silent pin. |
| **LESSONS** | L-12, L-32, L-34, L-40, L-41 |

---

### Stage 5 shadow (permit=None) — before enablement

### WP-17 — Shadow deploy ≥30 covered station-days (stage 5)

| | |
|---|---|
| **Title** | Compose forecast family with `permit=None`; write own offer tape |
| **Deliverables** | Node composes `ForecastLadderStrategy` via WP-11b `composition_kind` (sending id may still be `pm_us_crh_cont` until Stage 4). Forecast family gets `permit=None`. Shadow trials **never feed a verdict** (PREREG v3 §2:27; E4). ≥30 **covered** station-days (§7.12) — “covered” requires WP-0e **and the recorded ING-1 replace-vs-extend choice** (NB-2). Secondary endpoint = this family’s tape (§9). No displacement-shadow path (E4 YAGNI). **WP-34 runs here** (SEQ-2): first production boot of the NBM actor is verified by L-45 coverage count. |
| **Owner** | O (enable composition of the forecast kind as shadow, not orders) + B (WP-11b/14) |
| **Depends on** | WP-15 family_id on the tape, WP-16, **WP-0a/0b PASS**, WP-0e/L-45 for “covered” |
| **GATE** | **PASS:** ≥30 covered station-days with ladder-scan **and** NO-path live (starts 15-day 0-fill clock, §9); WP-34 empty-diff on first boot. **CONTINUATION:** node dead / tape empty → clock is MISSING (L-38); fix WP-0a, do not start Stage 4; extend shadow (**owner O/B**). Incomplete days excluded (§4.6). |
| **Size** | elapsed ≥30 calendar days (eng S to wire) |
| **Risks** | WP-0 zombie makes this a no-op. Coverage 0/15 (PROGRESS:86) until ING-1. |
| **LESSONS** | L-38, L-20, L-45, L-26 |

### WP-34 — L-45 boot-coverage count for the forecast ingest actor  **[R1-10] [SEQ-2 — at WP-17]**

| | |
|---|---|
| **Title** | First live boot of the NBM actor is verified by coverage count, not “no ERROR lines” |
| **Deliverables** | After first production boot of `nbm_forecast_actor` (**this is WP-17’s first shadow boot**, not a post-arming act): count catalog/station roots with ≥1 `ForecastPoint` vs the subscribed station list; `comm -23` empty-diff (L-45). Distinct from recorder L-45 (WP-0c/0e) — this is the **ingest actor’s** first boot. |
| **Owner** | B/O |
| **Depends on** | WP-12 live actor + **WP-17 first production boot** |
| **GATE** | **PASS:** empty-diff on first boot. **CONTINUATION:** missing stations → do not call the day “covered”; fix transport/pacer/host (**owner B**); WP-32 alerts `forecast_unavailable`. |
| **Size** | S |
| **LESSONS** | L-45, L-8, L-38 |

### WP-18 — Pre-Stage-4 on shadow tape (stage G)

| | |
|---|---|
| **Title** | Recompute WP-7’s historical §4.5 gates including live shadow would-takes |
| **Deliverables** | Same four gates as the WP-7 historical artefact; now accumulated through shadow + secondary tape (§4.5). Confirmatory statistic **only on post-freeze 2026 data** (MULTIPLICITY_RULE v). Do not invent a third corpus. |
| **Owner** | B; prediction-market + mle |
| **Depends on** | WP-17 ≥30d, WP-7 historical artefact |
| **GATE** | **PASS:** all four PASS. **CONTINUATION (R1-5, amendment §B):** fail → extend shadow, then re-run with the **next WP-7 frozen variant** (must have been pre-declared; cannot invent one after seeing shadow) (**owner B**). Arming refused only while every variant fails. INSUFFICIENT-DATA → extend shadow. |
| **Size** | S (compute) + elapsed |
| **LESSONS** | L-21, L-38 |

---

### Stage 4 arming — operator-only enablement

### WP-19 — Arm `pm_us_crh_fc_v1`; displace `pm_us_crh_cont` (stage 4)

| | |
|---|---|
| **Title** | Operator enablement of the forecast family as the sole sender (**env/manifest, not a source edit**) |
| **Deliverables** (§8, E4, ruling:11, WP-11b): O sets `sending_family_id=pm_us_crh_fc_v1` (REGISTERED). Positive control: rest-and-cancel. **Build-side** must already have WP-18 PASS. Supervisor self-check follows the new id (F1). |
| **What displacement means for `pm_us_crh_cont`’s sequential test** | Per **E4 + ruling:11**: `pm_us_crh_cont` is **NOT composed**. Trial **CLOSED** at displacement, terminal state **`SUPERSEDED-BY-RULING`** (neither KILL nor SURVIVE). `S_k`, n, clocks **frozen** and written by the scorer. Shadow trials never fed a verdict anyway. This is a **product decision** that forecasting is the strategy, **not** a statistical verdict on CRH. §9’s CRH 15-day clock row is **deleted** (E4). Forecast family’s **own** 15-day clock and LD-OBF start from its D0/n=0. |
| **KILL continuation after arming (R1-2, amendment §B) — verbatim non-laundering** | A sequential-test KILL of the armed forecast champion does **not** return to the observation family. Continuation = the learning loop’s challenger path (WP-20..26). **Non-laundering clause:** (a) a post-KILL challenger may be armed **ONLY** if it was already promotion-eligible (**all six** §13.3 criteria logged in the ledger) **BEFORE** the KILL tripped **or was pending** — criterion 5 (KILL-pending refusal) is **never overridden**; (b) arming the new `family_id` is **operator-only** (D11, ruling:13); (c) the KILLed champion’s `S_k`/n are **frozen and never reused**. If no pre-eligible challenger exists, the node goes `permit=None` on last-good (shadow) and the loop continues to mint challengers — it does **not** re-arm `pm_us_crh_cont`. |
| **Owner** | **O only** (enablement + two caps, name-only). B does not flip live flags. |
| **Depends on** | WP-18 PASS, WP-15 REGISTERED, WP-0a/0b PASS, WP-11b, positive control |
| **GATE** | **PASS:** positive control succeeds; exclusivity holds (one sending id); CRH scorer writes SUPERSEDED-BY-RULING snapshot; supervisor self-check block **runs** for fc_v1 (F1). **CONTINUATION:** fail positive control → **that arming attempt** halts; diagnose, fix, retry (**owner O**). Fail exclusivity → do not enable. Never a programme STOP; never a source edit to “force” the family on. |
| **Size** | S |
| **Risks** | First forecast-conditioned **legal** order is **this day**. Residual/AMBIGUOUS path is still v3 resolver (not redesigned here). |
| **LESSONS** | L-22, two-caps, NO-SEND untouched, `allow_short=False` |

---

### Stage 5+ learning loop (champion must be PREREG-registered — §0.2, §13)

Components **built** after WP-15; they **must not promote** until the six criteria hold. Online/in-Strategy update: **NONE EXISTS** (§13.2) — BUILD out-of-process. **Critical path for A(2): (a) + registry + shadow scoring + engine + CombinedDraw loader + family-parameterised jobs + replay pin.** §13.1 (b)(c)(d)(e) deferred to post-first-promotion (non-blocking).

To satisfy A(2) “refits from SCORED TRADE OUTCOMES” with (c) deferred: **WP-21 (a) joins admissible scored fills + settlement + forecast rows**, not cache-only climatology.

### WP-20 — Artefact registry + learning ledger (stage 5+)  **[R1-3]**

| | |
|---|---|
| **Title** | Distinct exact-set schema for champion/challenger artefacts |
| **Deliverables** (§13.3–§13.4): registry fields `artefact_id, component ∈ {density_table, error_calibration, market_recalibration, execution_policy, window_policy}, sha256, git_sha, corpus_span, fit_date, parent_revision, status ∈ {CHAMPION, CHALLENGER, REJECTED, RETIRED}, promoted_at, rejected_reason, boundary_inputs_sha256`. **Distinct** from `FamilyManifest` (bolted-on fields would fail exact-set). Ledger: append-only, one row/cycle, `decided_by="rule_engine"`, explicit serialization, `dataclasses.asdict` banned. **Admissible-only fill rows (R1-3):** ledger/join excludes `duplicate_fill`, `q≠1`, `fee_unreconciled` resolver fills — same filter PREREG v3 §5 uses for the sequential test. `lint-imports`: `strategy.*` must not import nightly fit modules. |
| **Owner** | B; python-reviewer |
| **Depends on** | WP-15 (champion registered) |
| **GATE** | **PASS:** unpinned `boundary_inputs_sha256` refuses promotion (mirrors `family_manifest.py:180-184`); residual fills cannot enter the ledger (RED). **CONTINUATION (R1-5):** unpinned → rerun WP-29 for the challenger’s own corpus (**owner B**). Residual leak → fix the filter, do not promote. |
| **Size** | M |
| **LESSONS** | L-12, L-21, L-34 |

### WP-31 — CombinedDraw loader from scored-trial parquet  **[R1-10]**

| | |
|---|---|
| **Title** | Criterion (2) has a real loader, not an assumed one |
| **Deliverables** | Read `derived/scored_trials/<family_id>/scored_trials_*.parquet` → filter **admissible** (R1-3) → `StratumRow` → `combine_station_day` → `CombinedDraw` (`current_rung_hold_v2.py:196-345,348-364`). Used by WP-26 criterion (2) and WP-7/18. No second statistic. RED: a residual (`fee_unreconciled` / `q≠1` / `duplicate_fill`) is dropped; an admissible fill becomes exactly one constituent of the station-day draw. |
| **Owner** | B; prediction-market-reviewer |
| **Depends on** | WP-20 schema (admissible filter), existing scorer parquet |
| **GATE** | **PASS:** loader round-trip against the 09-16 admissible n=3 fixture (L-42: parquet written by the real scorer, not a hand-built `CombinedDraw`). **CONTINUATION:** schema drift → widen the exact-set adapter in the same commit (L-12); do not silently coerce. |
| **Size** | S |
| **LESSONS** | L-42, L-12, L-40 |

### WP-21 — §13.1a density-table nightly refit (stage 5+, **on A(2) critical path**)

| | |
|---|---|
| **Title** | Challenger density tables from settled forecast rows **and admissible scored fills** |
| **Deliverables** | Nightly batch; only `available_at_ns ≤ decision time`; only SETTLED station-days; same §7.5 alphabet/key; walk-forward `train_end_exclusive`. **A(2) join:** outcomes from WP-31 admissible scored fills + CLI settlement, not cache-only. Forecast/R(t) still from WP-3 cache + WP-12 catalog. Output = a **new density artefact file** (F2), not a src patch. |
| **Owner** | B |
| **Depends on** | WP-20, WP-31, WP-3, WP-13 freeze as parent |
| **GATE** | **PASS:** leakage RED. **CONTINUATION:** fail → artefact REJECTED, not loaded (**owner B**). Empty scored store → component idle, not fabricated (same as §13.1c tape-empty rule). |
| **Size** | M (with WP-27) |
| **LESSONS** | L-13, L-21 |

### WP-22 — §13.1b forecast-error calibration — **deferred, not on critical path**

Nightly `fit_error_model` by station×season×lead; `calibration.py:60-103` `train_end_exclusive` verbatim; not a live Strategy call. Depends on WP-12/WP-20. Same leakage RED. Size S–M. Post-first-promotion.

### WP-23 — §13.1c market-conditioned recalibration — **deferred, not on critical path**

Reliability/isotonic vs contemporaneous ask vs settled outcome; own offer tape ⨝ CLI; named component; cannot learn counterfactual fills (§13.5). Size M. Post-first-promotion. (A(2) scored-outcome refit is carried by WP-21+WP-31, not this row.)

### WP-24 — §13.1d execution learning — **deferred, not on critical path**

Liftability/fill-rate/slippage + `no_bid_side` by hour×ask×station; Depth10 via both adapters; gated on SETTLED; QuoteTick-only invalid (L-35). Depends on WP-0e. Size M. Post-first-promotion.

### WP-25 — §13.1e window/hour policy — **deferred, not on critical path**

Challenger `window_*_hour_lst`; same holdout and promotion rule; never applied in place (L-34). Size S. Post-first-promotion.

### WP-26 — Promotion engine (stage 5+)  **[R1-2, R1-3] [F3]**

| | |
|---|---|
| **Title** | Pre-declared six-criterion promoter that **WRITES** the DRAFT family manifest + density artefact + sha; rollback-as-new-revision; **no source edit** |
| **Deliverables** (§13.3): score ≥K challengers (K from WP-8, INFERRED 3) on the **same** offer-tape rows; never live order flow. **ALL must hold:** (1) `Brier_challenger ≤ Brier_champion − δ_promote` AND `ECE_challenger ≤ ECE_champion` in mid-p bucket. (2) **Paired** realized-edge on **admissible** CombinedDraws (WP-31, R1-3): `edge_hat=Σx/Σqty`, `SE=sqrt(I)/Σqty`; CI-LOWER vs CI-LOWER; challenger CI-lower > 0 AND not worse than champion’s on the **same** days **within `tol_not_worse` (WP-8)**; plus station-day block bootstrap. **Would-take wording:** the paired set is **champion fills that are also would-takes under the challenger’s legality policy**; **no counterfactual challenger rows** (§13.5). (3) `N_promote` station-days since `fit_date` (INFERRED 150). (4) ≤1 promotion per family per `M` days (INFERRED 30). (5) **KILL-pending refusal:** any §9 KILL tripped or pending next LD-OBF look → REFUSED this cycle. (6) real `boundary_inputs_sha256`. Any failure → NOT PROMOTED, ledger names the criterion. **F3 CONCRETE DELIVERABLE — the engine WRITES:** (i) `deploy/families/{new_family_id}.json` with `status=DRAFT_NOT_REGISTERED`, `composition_kind=forecast_ladder`, new prefix/D0, n=0, `density_artefact_path`, `density_artefact_sha256`; (ii) the density artefact file; (iii) the sha. Clocks restart. **Operator residual (D11), not this WP:** flip DRAFT→REGISTERED, set `sending_family_id`, `systemctl --user enable --now breezy-family-tally@<id>.timer`. Rollback on champion drift: mark REJECTED; `permit=None` on last-good; **mints a new revision** (engine writes another DRAFT, not in-place). Fee θ pinned via WP-0d capture-test, band 0.05–0.95, two caps unchanged. **No new operator knob** (§13.3) — **live enablement of a new family_id remains operator-only** (D11, ruling:13). **R1-2 non-laundering** binds here: criterion 5 is never overridden to launder a KILL. |
| **Owner** | B; prediction-market + python-reviewer |
| **Depends on** | WP-20, WP-21, WP-27, WP-31, WP-15 champion, **admissible fills** for criterion (2) |
| **GATE** | **PASS:** RED tests WP-28; a promotion-eligible fixture produces the three on-disk files and **zero** `src/` hunks. **CONTINUATION:** fail a criterion → not promoted (never relax; relaxing is an estimand change, §13.6). No challenger in `T` days (INFERRED 90) → one ledger line, no other action. KILL of champion → §B/WP-19 continuation (pre-eligible challenger or shadow last-good). |
| **Size** | M |
| **LESSONS** | L-21, L-34, L-7, L-43, L-12 |

### WP-27 — Nightly jobs / timers with **measured** headroom (stage 5+)  **[R1-10] [F5]**

| | |
|---|---|
| **Title** | systemd oneshots for refit, shadow-score, promote, replay — **timetable, not an assertion** |
| **Deliverables** (§13.2, §13.4, §11): sibling of `deploy/systemd/breezy-mb-daily.timer`/`.service` (`OnCalendar`, `Type=oneshot`, `MemoryHigh=12G`/`MemoryMax=16G`, `Slice=breezy-studies.slice`, `TimeoutStartSec=3600`). **Never** share slice with `breezy-trade-supervisor.service` (uncapped). One heavy job at a time. Egress-scope review per job. Tally via WP-11b template `breezy-family-tally@pm_us_crh_fc_v1`. Score driver already enumerates REGISTERED families (`score-live-trials-run.sh`) — must write `derived/scored_trials/pm_us_crh_fc_v1/`. |
| **MEASURED memory (do not assert stagger)** | `breezy-mb-daily.service:29-44` journals last three completed runs at **14.3G / 10.1G / 11.6G** under `MemoryHigh=12G`/`MemoryMax=16G`. Review figure: a single study already peaks **12.1G + 5G swap** under the 16G cap. Five new jobs + engine + tally **cannot** share that window by assertion. |
| **F5 — 18:30Z vs the live node** | The 18:30Z promotion-engine slot runs **while the live node is active** (fills observed 18:00–20:12Z on 09-15; live window 16:50–01:00Z). Deliverable = a **measured-headroom check of that job against the concurrently running supervisor/node** (RSS/journal of both), **or** a MemoryHigh cap + slot rule that keeps the study off the node’s working set. Measuring only vs mb-daily is not enough. |
| **Live-node-protection response (16:50–01:00Z)** | If study peaks approach host capacity during the live window: **stop the study, never the node.** Encode as unit `OOMPolicy` / slice + an explicit operator/runbook line: kill `breezy-studies.slice`, leave `breezy-trade-supervisor.service` running. First production week: log memory peak of **node + study** at 18:30Z; if combined peak would threaten the node, the 18:30 job **moves** to 04:30+ (after mb-daily), not into the live window. |
| **Concrete `OnCalendar` timetable (required deliverable; revise if a job’s measured peak + mb-daily **or live node** would overlap)** | UTC: **14:15** `breezy-score-live-trials` (existing, small). **15:00** WP-21 density refit (after score, before tally). **16:00** challenger shadow-score. **17:25** `breezy-family-tally@%i` (existing cadence). **18:30** WP-26 promotion engine (after tally + shadow-score) — **subject to F5 live-node headroom**. **02:00** WP-33 champion replay pin. **03:00** `breezy-mb-daily` (existing heavy; **do not** start any new heavy job after 01:00 or before 04:30). Slice: one of {refit, shadow-score, promote, replay, mb-daily} at a time. First production week: log `memory peak` per new unit; if any new job peaks >8G, it **moves** to 04:30+ (after mb-daily), not into the 14–19Z cluster. |
| **Owner** | B; python-reviewer + security-reviewer |
| **Depends on** | WP-20 schema, WP-11b template, WP-0b pattern |
| **GATE** | **PASS:** L-16-equivalent: job failure is journal-loud, exit ≠0, no swallowed raise; timetable committed; first-week peaks recorded **including node+study at 18:30Z**; live-node-protection response is in the unit/runbook. **CONTINUATION:** OOM/swap → move the offender per the rule above (**owner B**); if the conflict is with the live node, **stop the study** (F5), never the node; loop is MISSING (L-38) until the job actually completes, not until the unit file exists. |
| **Size** | M |
| **LESSONS** | L-16, L-26, L-38, L-45 |

### WP-28 — Promotion RED tests (stage 5+)  **[F2]**

| | |
|---|---|
| **Title** | Leakage, determinism, rule, rollback-as-revision, KILL-pending, **no-src-edit promote** |
| **Deliverables** (§13.4, §11 last row): Brier-winning + edge-CI-failing challenger is **not** promoted; ledger names criterion; rollback mints new `family_id`; promotion while §9 KILL pending is refused; residual fill does not enter criterion (2); `lint-imports` rule itself; **promoting fc_v1→fc_v2 changes ONLY manifest + artefact files** (F2) — `test_promoting_fc_v1_to_fc_v2_changes_only_manifest_and_artefact_files` asserts a promotion fixture’s diff is `deploy/families/pm_us_crh_fc_v2.json` + the density artefact named in it (+ ledger row); **zero `src/` hunks**. |
| **Owner** | B; python-reviewer sign-off mandatory |
| **Depends on** | WP-26 |
| **GATE** | **PASS:** all RED→GREEN on integration branch. **CONTINUATION:** fail → engine must not run in production timers; fix (**owner B**). |
| **Size** | S |
| **LESSONS** | L-43, L-21, L-34, L-12 |

### WP-32 — Stale-forecast / high-refusal-rate alerting  **[R1-10]**

| | |
|---|---|
| **Title** | `forecast_stale`, `forecast_unavailable`, `no_bid_side` are visible stops, not silent counters |
| **Deliverables** | Alert when (i) `forecast_unavailable` persists across a whole in-window station-day, (ii) `forecast_stale` rate exceeds a pre-declared fraction of scans, (iii) `no_bid_side` rate exceeds the §4.10 baseline by a pre-declared margin. Reuse `runtime.health` / `AlertPayload` (already used in `app/trade.py:76-93`). L-38: a stop that cannot fire is missing — these refusals must be able to increment **and** page. |
| **Owner** | B |
| **Depends on** | WP-14 COUNTER reasons exist |
| **GATE** | **PASS:** RED: inject unavailable/stale/empty-bid → alert fires; a healthy window does not. **CONTINUATION:** alert path broken → treat as MISSING stop (L-38); do not arm / do not count the day. |
| **Size** | S |
| **LESSONS** | L-38, L-30 |

### WP-33 — Champion replay pin  **[R1-10]**

| | |
|---|---|
| **Title** | Nightly byte-identical replay of the frozen champion on its own tape |
| **Deliverables** | Oneshot (WP-27 02:00Z): replay the champion **artefact** on that day’s offer tape; assert byte-identical take set / `model_p` vs the live COUNTER log. Drift → champion REJECTED (Stage 2 monitor sibling), last-good shadow, **new revision + new artefact** (L-34, F2). |
| **Owner** | B |
| **Depends on** | WP-17 tape, WP-13 freeze, WP-27 slot |
| **GATE** | **PASS:** identical replay on a fixture day; a mutated artefact fails RED. **CONTINUATION:** mismatch → do not promote, do not keep sending a drifted champion; rollback-as-revision (WP-26). |
| **Size** | S–M |
| **LESSONS** | L-21, L-34, L-43 |

### WP-30 — Forecast-family scorer/tally/PROGRESS hygiene (stage 5 / 4)

| | |
|---|---|
| **Title** | Do not repeat CRH’s missing-stop and stale-n failures |
| **Deliverables** | Score+tally for `pm_us_crh_fc_v1` from D0 via **existing** scorer enumerator + WP-11b tally template (no new per-family copies). PROGRESS n updated from tally (not frozen). 15-day clock **increments** (positive control: a day that should count, counts — L-38). |
| **Owner** | B/O |
| **Depends on** | WP-15, WP-27, WP-11b, WP-0c pattern |
| **GATE** | **PASS:** first look machinery can fire. **CONTINUATION:** fail → forecast sequential test is MISSING (L-38); do not claim a running clock; fix the wrapper/template (**owner B**). |
| **Size** | S |
| **LESSONS** | L-38, L-5, L-45, L-20 |

---

## 3. Critical path and parallel groups

```
WP-0a  ║  WP-1 (IEM probe)  ║  WP-2 (NOMADS probe)  ║  WP-0e ING-1 (choice before "covered")
  │
  ├─ WP-0b/0c/0d  ║  WP-11b registry (SEQ-1: ∥ 0b, after 0a, OFF the WP-10 chain)
  │
         WP-3 (1-min cache)   WP-4 (climate-day freeze)  [both need WP-1]
                \             /
                 WP-5 0a PASS or §B(i)(ii)(iii)
                         │
              WP-6 fit ── WP-7 MULTIPLICITY_RULE + PIT/cheap screen
                           + historical §4.5 artefact (folded WP-9)
                           ── WP-8 power table (incl. tol_not_worse)
                         │
                 0b PASS / INSUFFICIENT / next variant / S if K_variants exhausted
                         │
     ┌───────────────────┴──────────────────┐
     WP-10 ladder_ev     WP-12.0 L-1 notes + WP-12 ingest (D13: build ∥ 0b)
                 └──────┬───────────────────┘
                    WP-13 freeze  (density DATA artefact; needs WP-11b keys)
                              │
                    WP-14 strategy + WP-16 test (RED first, + differential)
                              │
                    WP-29 Var(S) + WP-15 PREREG v6
                              │
                    WP-17 shadow ≥30d  + WP-34 ingest-actor first-boot count
                              │  (WP-0a/0b PASS, WP-0e covered + ING-1 choice)
                    WP-18 pre-Stage-4 on shadow  ── fail → next WP-7 variant / extend
                              │ PASS
                    WP-19 Stage 4 ARM  ← O enablement (sending_family_id=fc_v1)
                              │
         WP-20 registry ∥ WP-31 CombinedDraw loader ∥ WP-32 alerts
                              │
         WP-21 (a) refit from scored outcomes → new density artefact
                              │
         WP-27 timetable (F5 live-node headroom) → WP-26 engine WRITES DRAFT
              manifest+artefact+sha → WP-28 tests → WP-33 replay pin → WP-30 hygiene
                              │
         first PROMOTION (decision) ≥ N_promote station-days AND enough admissible CombinedDraws
         engine has written deploy/families/fc_v2.json DRAFT + artefact + sha
         first challenger SEND = that decision + O: DRAFT→REGISTERED,
              sending_family_id=fc_v2, enable breezy-family-tally@fc_v2.timer
              (no src/ edit)

deferred off path: WP-22 (b), WP-23 (c), WP-24 (d), WP-25 (e)
```

**Strictly serial for arming:** 0a PASS-or-§B → 0b PASS (frozen variant) → (3.0 → freeze → strategy → PREREG) → shadow ≥30d → pre-Stage-4 PASS → Stage 4. **WP-11b ∥ 0b after WP-0a; not on the WP-10 chain.** **Stage 1 build ∥ 0b (D13); if S refuses D13, WP-12 waits on 0b.** **Promotion criteria (2)(3)** serial after **armed admissible fills**.

**Parallel:** WP-0a–0e ∥ WP-1 ∥ WP-2; WP-11b ∥ WP-0b after WP-0a; WP-3 ∥ WP-4 after WP-1; WP-10 ∥ WP-12 after 0a source chosen (WP-11b already landed); WP-20/31/32 after WP-15 ∥ shadow; WP-34 **at WP-17**; WP-21 after WP-20/31 ∥ live; WP-22..25 after first promotion.

**Earliest legal forecast-conditioned order:** Stage 4 arming instant (WP-19), after 0b PASS **and** pre-Stage-4 PASS **and** PREREG v6 **and** ≥30 shadow station-days **and** WP-0a/0b node PASS **and** operator enablement. Order of magnitude: **~6–10 weeks after 0a probes run**, if every gate PASSes first try; any INSUFFICIENT-DATA / variant / K_variants ruling extends without bound.

**Earliest learning-loop promotion (restated from measured fill rate):** Criterion (2) needs **admissible CombinedDraws from fills**, not counterfactual tape. Observed **~0.27 admissible fills/day**. `N_promote` INFERRED 150 station-days is **not** the binding constraint: 4 stations × 38 calendar days ≈ 152 station-days but only ~10 fills at the measured rate — too few for a paired CI. Binding horizon ≈ `n_fills_needed / 0.27` calendar days after Stage 4, with `n_fills_needed` set by WP-8. Do **not** quote “~38 days after Stage 4.” Challenger Brier/ECE scoring can **start in shadow**; **promotion cannot**. First promoted challenger **sending** additionally requires D11 (O: DRAFT→REGISTERED + `sending_family_id` + tally timer). The engine has already written the DRAFT files.

---

## 4. Decision points for the operator

| # | Decision | Evidence shown | If no / fail |
|---|---|---|---|
| D0 | Already given: forecasting is the strategy; self-learning required | Ruling 09-18; supersedes PROGRESS:30 KILL | — |
| D1 | Run WP-1 and WP-2 (triple unlock, user-agent, `BREEZY_LIVE=1`) | Probe scripts’ containment docs; L-46 | 0a cannot PASS; §B(i) unavailable |
| D2 | WP-0 restore (marker/reap/tally env/fee capture/ING-1) — **ops, not a strategy choice** | Audit §5; amendment §C; `self_check` `:83,432-486`; `Popen` `:588-615,920-933` | No sending, no looks, A(3) false |
| D3 | Accept 0a PASS **or** a recorded §B branch (NBM-direct / GFS / reduced stations) | Four-station NBS TSV; WP-2 q’s; surviving `stations` | All three §B fail → S ruling |
| D4 | Accept 0b PASS / INSUFFICIENT / next variant | Cheap-screen tables **for every pre-declared variant**; Holm-Bonferroni/FDR; PIT two-lag; Brier/ECE vs WP-8; takes/day; `no_bid_side` | `K_variants` exhausted → S ruling |
| D5 | Ruling only if WP-8 cannot identify a constant from 0b | Power table (incl. `tol_not_worse`) | No PREREG v6 |
| ~~D6~~ | **Removed (R1-8).** L-46 option (a) is WP-12c, a build WP. | — | — |
| D7 | Register PREREG v6 (`d0_climate_day`, boundary sha, density artefact sha) | WP-16 green, Var(S) report, frozen artefact sha, WP-8 constants | No fills |
| D8 | Pre-Stage-4 go/no-go (WP-18) | Wilson-UPPER vs mean(BE) mixed + per side; 0-take operational kill; calibration drift | Next WP-7 variant / extend shadow; refuse Stage 4 while every variant fails |
| D9 | **Stage 4 enablement** (set `sending_family_id=pm_us_crh_fc_v1`) + two caps **by name only** | D8 pack; positive-control rest-and-cancel; exclusivity; CRH close snapshot; supervisor self-check runs for fc_v1 (F1) | Do not arm |
| D10 | Accept CRH terminal `SUPERSEDED-BY-RULING` (closes n=3 CONTINUE mid-stream) | Frozen S_k/n from last good tally (09-16: n=3, −0.82) plus any recovered 09-17+ | Product decision already in ruling; still confirm freeze artefact |
| **D11** | **Arm a promoted revision — operator residual only.** Engine has already written `deploy/families/{new_family_id}.json` as `DRAFT_NOT_REGISTERED` plus density artefact + sha (WP-26). O: (1) flip DRAFT→REGISTERED, (2) set `sending_family_id` to the new id, (3) `systemctl --user enable --now breezy-family-tally@<id>.timer`. Never a source edit. | Ledger row naming all six criteria **logged before any KILL pending**; engine-written DRAFT files; R1-2 (a)(b)(c) | Challenger stays shadow |
| D12 | Budgets: probe/backfill wall-clock; 16G study cap; **not** cap values (never assigned in-repo) | Job memory journals (`breezy-mb-daily.service:34-37`: 14.3G/10.1G/11.6G; review 12.1G+5G swap); **F5 node+study at 18:30Z** | Throttle/move jobs per WP-27 timetable; **stop the study, never the node** |
| **D13** | **One-line ruling amendment:** “Stage 1 may be BUILT pre-0b; registration and arming still require 0b PASS.” | Shortens critical path by the length of 0b; Rev 5 ruling:13 currently says Stage 1+ requires 0b PASS | **Conservative fallback (NB-3):** S refuses → WP-12 wait-on-0b (r1 sequencing); A still reachable, slower. Ingest code may be written under this plan’s D13 but not registered/armed until the amendment is filed **or** 0b PASSes. |

Operator-only remains: **live enablement and the two caps**. Promotion math is build-side (§13.3). The engine writes DRAFT files; O flips REGISTERED / env / timer. Nothing else is an operator knob (ruling:13). **D6 is gone.**

---

## 5. Explicitly NOT in scope / not promised

- **Edge existence or ROI.** G-02 NO-GO still stands (`PROGRESS.md:28`). 0b/pre-Stage-4 may exhaust `K_variants` and escalate a ruling. “Winning” is not a plan output.
- **Backtest-ROI claims** (§1 non-goals). Tape screens, never historical ROI (§12 row 9).
- **Kalshi** (§1.6).
- **Edits to `pm_us_crh_cont` decision files** (`continuous_strategy.py`, `tick_eval.py`, CRH `decision.py`, `archive_table.py`).
- **Sizing** beyond `order_quantity=1`; Kelly remains locked (`config.py:144-146`).
- **`allow_short=True`**; NO is `OrderSide.BUY` on `^no`.
- **NO-SEND / live-enablement code paths** touched by build. WP-11b changes **which id** is composed, not the permit mint.
- **A third operator cap** or any assigned cap value. `sending_family_id` is a build-side flag replacing two existing booleans, not a reserved cap (L-39).
- **Online / in-node model update** (does not exist in Nautilus; will not be built — §13.2).
- **Intraday exit** for this family (UNARMED unless a later ruling; EXIT-1 is a separate PROGRESS row).
- **Resting-bid / band-decider / MP-B qty>1** (separate families/rulings; G-R1/2/4/5 FAIL, R-11).
- **Open-Meteo, NAM MOS, HRRR, ECMWF** (§3.1).
- **`mode='full'`** (stays refused; forecast is a distinct mode).
- **CRH SURVIVE/KILL** at displacement — closed SUPERSEDED-BY-RULING, not a statistical call.
- **That the learning loop will promote anything** (§13.6: T-day silence is a ledger line, not a threshold relaxation).
- **§13.1 (b)(c)(d)(e) on the path to first promotion** (deferred; A(2) met by (a)+registry+shadow-score+engine+WP-31+WP-11b).
- **r1 WP-11 three-boolean exclusivity.**
- **r2 WP-9 as a separate package** (folded into WP-7).

---

## 6. Open questions the plan cannot settle from the repo

1. **Will 4-station 2021→now NBS overlap PASS?** Only KMIA is verified in the ruling (667 rows / 160 TXN 2026-09-10..17). WP-1 is the measurement; §B is the continuation.
2. **δ, ε, δ_promote, `tol_not_worse`, N_promote, K, M, T, K_variants, Holm vs FDR q** — INFERRED until WP-7/WP-8. Not in the repo as measured values. `K_variants` and the Holm/FDR q **must be declared before the first WP-7 run**. `tol_not_worse` is pinned in WP-8 next to `δ_promote` (NB-1).
3. **Does D13 get the one-line ruling amendment?** Until yes, WP-12 **build** still proceeds under this plan’s D13; **registration** waits on 0b. **Conservative fallback if S refuses D13 (NB-3):** build wait-on-0b (r1), A still reachable, slower.
4. **`_maybe_submit` exact line range** for NO BUY — carried UNVERIFIED for Stage 3 (§1.2, §12). Three reviewers corroborated shape; still re-read before WP-14.
5. **`SyntheticBinaryTape` one-sided book** — confirm or extend before WP-16 (E7).
6. **Var(S) of mixed-side CombinedDraw vs `gs_boundary_pm_us_crh_v2.json`** — unknown until WP-29.
7. **`max_body_bytes` and systemd ingest-unit directives** — RE-VERIFY from WP-2 payloads before WP-12 (§5, §12).
8. **Pre-existing `test_forecast_edge_backtest.py` contents vs §7.13 names** — reconcile at Stage 3 start (§10).
9. **ING-1 replace-vs-extend** — WP-0e **records the choice** before WP-17 may claim “covered” (NB-2); catalog trap 1/2 constrain the repair (WP-12 RED tests apply to Depth10 too if it is identifier-less custom data).
10. **Trial frequency under the forecast family** still UNMEASURED until §4.10. Promotion horizon uses the **observed 0.27 admissible fills/day** as the conservative baseline, not a 1-fill/station/day hope.
11. **Whether 09-17 scorer failed only on env or also on zombie `NO_NODE` preflight** (`score_live_trials.py:1402-1406` warns and continues on NO_NODE) — tally failed on env; scorer parquet absence may be a separate skip (`family-tally-v2-run.sh:106-108` marker). WP-0b+0c measure this.
12. **E2 vs un-edited §7.6 sentence** `intent_long_yes=(side=="yes")` — implementers must follow E2; a body-only reader will build the short-YES bug (`risk.py:732-751`).
13. **PROGRESS n=0 vs tally n=3** — file is over the 250-line budget; hygiene is WP-0c, not a forecast feature.
14. **IEM MOS lag (~40 h) vs NBM live** — if NBM live is down long enough that IEM is the only source, whole-°F / 40 h lag may fail PIT; that is a WP-7 INSUFFICIENT-DATA / WP-32 alert, not a silent degrade.

---

## 7. GOAL-STATE WALK  **[L-3; plan unfinished unless the last row is true]**

Re-run after F1–F6. Last row was **not** true in r2 because of F1 (supervisor family-hardcoded) and F2 (density table in `src/`). Both closed. F3 restates the operator residual so the last row names enablement acts only.

| WP | Contributes to | Remaining gap after it |
|---|---|---|
| WP-0a | A(3) honest node; A(1) can actually send; **unblocks WP-11b** | Node can be live; still no forecast, no loop, ING-1/fee/tally open |
| WP-0b | A(3) sequential test can fire | Looks possible; n/PROGRESS/fee/ING-1 still dirty |
| WP-0c | A(3) honest n + L-45 recorder | Ledger trustworthy for CRH; ING-1/fee still open |
| WP-0d | A(3) fee is data; A(1)/A(2) inherit a pinned theta | Venue theta captured; ING-1 still open |
| WP-0e | A(3) Depth10 coverage; A(1) shadow “covered”; A(2) later (d); **ING-1 choice recorded** | **A(3) inputs exist.** Still no forecast model, no forecast orders, no loop |
| WP-1 | A(1) source measurement | NBS overlap unknown; §B unbound until WP-5 |
| WP-2 | A(1) NBM-direct source + PIT lag; §B(i) | Live ingest URL/body/lag known |
| WP-3 | A(1) R(t); A(2) (a) cache | 0b can fit |
| WP-4 | A(1) climate-day labels | Wrong-map stations dropped, not fatal |
| WP-5 | A(1) station set + source branch | 0a closed or §B armed |
| WP-6 | A(1) p_fc artefact | Screen not yet run |
| WP-7 | A(1) variant frozen under MULTIPLICITY_RULE; historical §4.5 artefact (folded WP-9) | Confirmatory 2026 data still required for Stage 4 |
| WP-8 | A(1) PREREG constants; A(2) δ_promote / `tol_not_worse` / N_promote / K / M / T | Constants pinned |
| WP-9 | — SUPERSEDED; see WP-7 | — |
| WP-10 | A(1) `mode='forecast'` exists; loads density from artefact pin | No ingest, no strategy |
| WP-11b | **A(2) without a code change**; A(1) cardinality-1 send; **F1 supervisor family-agnostic**; **F2 density keys in exact-set**; **F4 `phase0_family_permits` retired**; **F6 halt = global under card-1** | Registry exists; forecast kind may still refuse until WP-14 |
| WP-12.0 | A(1) L-1 recorded | Notes only |
| WP-12 / 12c | A(1) `ForecastPoint` in catalog + actor-push; IEM fallback | Decider not yet wired; first boot count (WP-34) still due at WP-17 |
| WP-13 | A(1) frozen **DATA artefact** (F2); not a src constant | Strategy not composed |
| WP-14 | A(1) strategy can take | Integration proof + registration open |
| WP-16 | A(1) proof forecast **value** moves takes (R1-7) | Not registered, not armed |
| WP-29 | A(1) honest `S_k` | Unpinned → no register |
| WP-15 | A(1) PREREG v6 identity + density pin | Shadow/arming open |
| WP-17 | A(1) confirmatory tape; A(2) shadow-score input | Pre-Stage-4 not yet recomputed |
| WP-34 | A(3) ingest-actor coverage **at first production boot (WP-17)** | First boot counted |
| WP-18 | A(1) Stage-4 legality | **Build-side A(1) ready.** Remaining: O enablement |
| WP-32 | A(3) forecast refusals visible | Alerts exist |
| WP-30 | A(3) forecast tally/clock can increment | Sequential test not MISSING |
| WP-20 | A(2) registry + admissible ledger | No refit yet |
| WP-31 | A(2) criterion (2) loader | Engine can see fills |
| WP-21 | A(2) refit from scored outcomes → new density artefact | Challenger artefact can exist |
| WP-27 | A(2) the loop actually runs (measured timetable + **F5 live-node headroom**) | Jobs scheduled without OOM-by-assertion; study yields to node |
| WP-26 | A(2) promote under §13.3 by **WRITING DRAFT manifest + artefact + sha** (F3) | Promotion is a decision + D11, not a src edit |
| WP-28 | A(2) engine must not ship broken; fc_v1→fc_v2 = manifest+artefact only (F2) | Tests bind the rule |
| WP-33 | A(2) champion is the frozen artefact it claims | Replay pin live |
| WP-19 | A(1) **operator enablement** (`sending_family_id=fc_v1`) | Live forecast orders |
| WP-22..25 | post-first-promotion richness | Not required for A |
| **After every BUILD WP (all except WP-19 and D11)** | **A(1) ready-to-send** (supervisor self-check family-agnostic, F1). **A(2) loop can mint / shadow-score / promote** by writing DRAFT `deploy/families/{id}.json` + density artefact + sha; fc_v1→fc_v2 does not touch `src/` (F2, F3). **A(3) inputs trustworthy.** | **remaining gap: none, except operator enablement** — (WP-19) set `sending_family_id=pm_us_crh_fc_v1`; (D11) flip DRAFT→REGISTERED, set `sending_family_id` to the new id, `systemctl --user enable --now breezy-family-tally@<id>.timer` |

**WALK (L-3):** WP-0 restore ∥ 0a probes → 0a PASS-or-§B → **WP-11b registry ∥ 0b** (after 0a, off WP-10) → 0b PASS (frozen variant + historical §4.5 artefact) → build 3.0 + Stage 1 (∥ 0b, D13; wait-on-0b if S refuses) + freeze **as DATA artefact** + strategy + PREREG v6 → shadow ≥30d **+ WP-34 first-boot count** → pre-Stage-4 PASS → **O sets `sending_family_id=pm_us_crh_fc_v1`** → live forecast orders → nightly (a)+registry+loader+engine → promotion **may** mint v2 **iff** six criteria hold **and** R1-2 non-laundering holds → engine **writes** DRAFT manifest+artefact+sha → **O flips REGISTERED, sets `sending_family_id=pm_us_crh_fc_v2`, enables `breezy-family-tally@pm_us_crh_fc_v2.timer`**. No source edit after WP-11b. No bare STOP. A gate FAIL routes to the named continuation.

**Last row is true.** F1 closed the supervisor hole (arming fc_v1 actually runs self-check). F2 closed the density-in-`src/` hole (promotion edits manifest + artefact only). F3 named the engine’s write and the three operator residual acts. No remaining build act sits between “every WP done” and A.

---

*Anchors verified this pass via `codegraph_explore` `projectPath=/home/jon/breezy` plus direct read of the unindexed unit file: `app/trade.py:74,159-267,251`; `composition.py:230-244` (`phase0_family_permits`), `:247-281` (`phase1_family_permits`); `family_manifest.py:62-73` (`_REQUIRED_KEYS`), `:175-184` (boundary sha pin / `UnpinnedBoundaryArtefactError`); `settings.py:109` (`CONTINUOUS_RUNG_HOLD_VAR`), `:761-768`; `trade_supervisor.py:379-391` (`read_continuous_family_store_state`), `:394` (`continuous_rung_hold_env_active`), `:760` (`default_ports.continuous_family_active`); `trade_supervisor_core.py:108-109` (`CONTINUOUS_STARTUP_EVIDENCE_KEY`, `CONTINUOUS_FAMILY_HALT_KEY`); `trial_day_latch.py:280,315`; `deploy/systemd/breezy-trade-supervisor.service:109` (`Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1`).*


---

# ROUND-3 COORDINATOR AMENDMENT (binding; adopts the reviewers' prescribed fixes verbatim)

Review record: r1 REJECT / LOW / REQUEST_CHANGES → r2 HIGH / REQUEST_CHANGES / REQUEST_CHANGES → r3 architect REQUEST_CHANGES (three anchored edits inside WP-11b, below), trading-bot-architect APPROVE (one sequencing suggestion, below), prediction-market-reviewer HIGH at r2 with all its items unchanged in r3. The amendment closes the architect's items; with it the architect's own goal-state walk has no remaining source edit at arming or promotion.

## WP-11b additions (architect, round 3)
1. **Exact-files list gains `src/breezy/runtime/order_enablement.py:224-231`.** The permit mint requires `settings.current_rung_hold is True or settings.continuous_rung_hold is True` else `RungHoldNotReadyError`; with the two booleans deleted the mint would refuse every family. Change: `rung_hold_family = settings.sending_family_id is not None` (the registry-resolved id is the family gate; caps, enablement, and the NO-SEND firewall are untouched). RED test (eleventh): `test_permit_mints_for_a_forecast_sending_family_id`.
2. **Store keys:** `CONTINUOUS_STARTUP_EVIDENCE_KEY` (`"exec/polymarket_us/startup_evidence"`) is already family-agnostic and stays UNCHANGED (re-keying would orphan the live store record). Only `CONTINUOUS_FAMILY_HALT_KEY` (`"continuous_rung_hold/halt"`) becomes a function of `sending_family_id`; `clear_family_halt_cli.py` follows the same widen.
3. **`_REQUIRED_KEYS` widening migrates ALL FOUR manifests in the same commit** — `pm_us_crh_cont`, `pm_us_crh_v2`, `pm_us_crh_exit_v4`, `kalshi_crh_v1` — plus every `load_family_manifest` fixture (43 callers; `tests/unit/test_family_manifest.py`, `test_family_tally_v2*.py`, `test_persistence_exit_gate.py`). `composition_kind` gains legal values for the exit and Kalshi manifests (`exit_gate` and `kalshi_crh`; neither is a sending kind under this registry). `exit_gate.py:30-31`'s family allowlist is noted as a later widen (exit stays UNARMED). `deploy/systemd/breezy-pm-crh-cont-tally.timer` is retired with its service when the `@` template lands.

## Sequencing addition (trading-bot-architect, round 3)
WP-19's GATE gains a dependency on WP-32 (stale-forecast / `forecast_unavailable` / `no_bid_side` alerting live and tested): Stage 4 enablement is refused while the alert path does not exist. WP-27 notes that `breezy-trade-supervisor.service` stays outside `breezy-studies.slice`.

## Goal-state re-walk after this amendment
After every build WP: the node boots from `sending_family_id` → `deploy/families/{id}.json`; the permit mints for any registry-resolved family; the supervisor self-check and halt key follow that id; promotion writes a DRAFT manifest + sha-pinned density artefact. Remaining gap: none, except the operator's three residual acts (flip DRAFT→REGISTERED, set `sending_family_id`, enable the family's tally timer).
