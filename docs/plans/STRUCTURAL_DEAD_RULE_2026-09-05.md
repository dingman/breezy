Commit: 8f76ecc9a3bb519b61db2e119aa5b05c8c315c58

# STRUCTURAL-DEAD rule automation — `pm_us_crh_v2` (2026-09-05)

**L-1.** Nautilus Trader **1.231.0** has no family stop, no covered-listed station-day, no structural-dead rule. Positive control: `class BacktestEngine` is in `.venv/lib/python3.13/site-packages/nautilus_trader/backtest/engine.pyx`; a tree search there for `structural.dead|covered.listed|station-day` is empty. Native surface that **does** apply: custom Data `QuoteTapeGap` (`src/breezy/adapters/polymarket_us/tape_records.py:51`, published `data.py:1846`, join via `resolved_gaps_by_seq`). Consume it. Do not patch NT. `allow_short` stays False. Do not assign operator caps. Do not touch live-enablement or the NO-SEND firewall.

**Registered wording (do not amend).** v2 §9 / v1 §5:105–106 / ratification (1)(f): window `[12:00,17:00)` LST; **afternoon-covered** = span of distinct captured Depth10/quote instants in that window `≥ 30` min (`0–1` instant ⇒ 0); **listed** = venue listed that station-day (skip-days out of the denominator, ~9%, `MISSING_COHORT_2026-09-02`); **denominator** = covered listed station-days of `{LAX,MDW,MIA,SFO}`; fire at count `≥ 15`; **≈0** = filled Takes `= 0` on those days — one fill defeats the stop (no ε). Distinct from D0+165. Manifest `deploy/families/pm_us_crh_v2.json`: `status=REGISTERED`, `d0_climate_day=2026-09-05`. Extra ε / Wilson-on-take-rate is a **rejected** new screen (v2 §12).

## 1. Spec vs code

| Spec piece | Code today | Gap |
|---|---|---|
| 15 / 0-fills KILL | `structural_dead()` `structural_dead_stop.py:100-121`; `MIN_STRUCTURAL_DEAD_STATION_DAYS` imported, never a second `15` | Pure verdict is correct. |
| Covered among listed | `covered_listed_station_days` `:129-167`; listed = `discover_station_days` (`ma_prelock_winner_ask_study.py:547-560`: any captured `tc-temp-{city}high-{day}-` dir in `[fetch_start,fetch_end]`) | **Listed ≡ captured.** Recorder-down with **zero** dirs is indistinguishable from venue-never-listed (`:141-155`). Conservative (undercounts, delays KILL) but cannot implement the 15-listed / 1-outage fixture. Partial afternoon capture can still span ≥30 min **across** a gap and false-count as covered. |
| Outage ≠ skip-day | `QuoteTapeGap` on tape; log `Quote tape gap #N OPENED` (`data.py:1806`) | Counter never reads gaps. `covers()` on the unresolved open row is all-future — consumers **must** use `resolved_gaps_by_seq`. |
| d0 scope | `--family-manifest` sets `fetch_start=d0` (`:266-278`); 14:15 `score-live-trials-run.sh:67-70` already writes `covered_listed_station_days_<date>.json` | End is `ASOS_FETCH_END` (`default_asos_fetch_end()`). Pre-d0 catalog days stay out. |
| v1 live KILL at n=0 | `live_family_tally.py:238-340` + CLI `--covered-listed-station-days` / `--fill-source`; wrapper `live-tally-run.sh:92-98` | Wired. Golden: `test_live_family_tally_structural_dead.py`. |
| v2 live KILL | `build_family_tally_v2` `:445-503` **can** call `structural_dead`, but `main()` `:939-946` never passes counts. `family-tally-v2-run.sh:81-85` does not pass JSON or fill-source. `structural_fired` is only an arg to `look_verdict` (`current_rung_hold_v2.py:184-209`) inside `range(look_step, …)` (`family_tally_v2.py:514-570`). At **n < 10** (today: n=0) `looks=[]`, `verdict` stays `CONTINUE`; `render_markdown_v2:861-872` prints that CONTINUE. `terminal_look` (`:221-248`) ignores `structural_fired`. **No `test_family_tally_v2*` names structural.** | **This is the automation hole.** |
| Live-only | `assert_family_only` (`family_barrier.py:47-74`); `_assert_live_provenance`; R2 empty store = n=0/CONTINUE not a refusal (`family_tally_v2.py:291-293`) | Paper/shadow/archive must not increment `filled_takes`. Fill-time source = `POLYMARKET_US_EXEC_STATE_DB`, never `len(scored)`. |
| REGISTERED gate | `render_markdown_v2:852-858` shadows DRAFT | Keep: no KILL/SURVIVE/CONTINUE vocabulary unless `status==REGISTERED`. |

**Covered listed station-day (target definition).** A `(station, climate_day)` with `climate_day ≥ d0` and station in the manifest census is **listed** iff the venue listed it (captured rung dir **or** a `QuoteTapeGap` for that day's instruments — subscription ⇒ listed). Skip-days (no cohort: `MISSING_COHORT` 2026-09-02 class) are **not listed**. It is **covered** iff listed **and** afternoon span ≥ 30 min **and** `[12:00,17:00)` LST does **not** overlap a resolved `QuoteTapeGap` interval. Recorder-down ⇒ not covered. Residual: process dead with neither dirs nor gap rows still looks like never-listed — fail closed (delay KILL). No live venue census call.

## 2. Design

**Where.** Keep counting in `structural_dead_stop.py` (14:15, once). Evaluate in `build_family_tally_v2` as an **additive KILL**, including when `n < look_step` / empty looks — not only inside `look_verdict`. Wire CLI + `family-tally-v2-run.sh` the same way v1 already wires `live-tally-run.sh`. Do not mutate v1's `build_live_family_tally` golden path except via the shared counter JSON.

**Inputs.** Manifest (`REGISTERED`, stations, d0); quote-tape catalog + `QuoteTapeGap`; fill-time count from exec-state since d0 (`filled_takes >= n_scored` or refuse). `provenance.json == live`.

**Verdict.** If not REGISTERED → SHADOW only. If REGISTERED and evaluable and `covered>=15` and `filled_takes==0` → **KILL** (even at n=0; R2 is a provenance rule, not a veto of this pin). One live fill → stop cannot fire. Else existing sequential CONTINUE/SURVIVE/KILL. Skip-print if `filled_takes is None` (fail closed).

**Idempotency.** Recompute from catalog+gaps+fill-source every 15:30 run; overwrite `family_tally_v2_pm_us_crh_v2_<date>.md`. No accumulators. Same JSON the 14:15 job already emits.

**Not this family.** Do not attach the pin to `kalshi_crh_v1`.

## 3. Build order (RED-first)

| Step | Hours | Change | RED test (file / name / assertion) |
|---|---|---|---|
| 1 | 3.0 | `covered_listed_station_days`: join `resolved_gaps_by_seq`; afternoon ∩ gap ⇒ not covered; JSON grows `outage_excluded_days` (observability only). Do **not** retouch the `15` literal. | `tests/unit/test_structural_dead_stop.py` — `test_listed_day_with_afternoon_gap_is_not_covered`: 15 listed tuples, 14 with 30-min span, 1 with overlapping `QuoteTapeGap` → `count==14`. Existing `test_15_covered_days_0_fills_is_dead` / `test_14_covered_days_0_fills_is_not_dead` stay green. |
| 2 | 2.0 | `family_tally_v2.py` CLI: `--covered-listed-station-days`, `--fill-source`, `--fill-since-climate-day` (mirror `live_family_tally.py:455-470`). `main()` passes them into `build_family_tally_v2`. | `tests/unit/test_family_tally_v2.py` — `test_15_covered_0_fill_time_kills_at_n_lt_look_step`: `build_family_tally_v2((), …, covered=15, filled_takes=0)` → `verdict=="KILL"` and render has `**KILL**` + `structural-dead`. `test_14_covered_0_fills_continues`. `test_15_covered_one_fill_time_fill_continues`. `test_draft_manifest_never_prints_kill`. |
| 3 | 1.5 | If `structural_fired` and REGISTERED, set `verdict="KILL"` **before** the look loop (and keep `look_verdict` injection). Render a structural line when evaluable, not only when SKIPPED. | Same file — `test_empty_looks_structural_kill_is_not_continue_n_lt_look_step`. |
| 4 | 2.0 | `family-tally-v2-run.sh`: require same-day JSON (shape-check like `live-tally-run.sh:47-80`); pass count + `POLYMARKET_US_EXEC_STATE_DB` + d0; refuse if `fetch_start != 2026-09-05`. | `tests/unit/test_family_tally_v2_deploy.py` — `test_wrapper_passes_covered_listed_and_fill_source` (stub python argv); `test_wrapper_skips_when_counter_json_absent`. |
| 5 | 1.0 | Paper/provenance: fill-source must not see `paper_replay` rows; v2 still `_assert_live_provenance`. | `test_paper_provenance_store_is_refused_before_structural_eval` (`test_family_tally_v2.py`). |

**Required fixtures (operator):** (a) 15 covered / 0 fills → KILL; (b) 14 covered / 0 fills → CONTINUE; (c) 15 listed with one outage day → covered=14 → CONTINUE. Reuse `_load_module()` + `_manifest()` conventions already in those test files.

**Gate:** `scripts/ci/run_tests_no_egress.sh`. Do not weaken `test_structural_dead_stop.py`, `test_live_family_tally_structural_dead.py`, family_barrier, or provenance tests.

## 4. Hours

~12 h total, amended per the adversarial review (docs/evidence/grok_structural_dead_plan_review_2026-09-05.md Q6): 4.0 (gap join + six-key contract) + 2.0 + 3.0 (render headline + terminal_look + filled_takes>=n refusal) + 2.0 + 1.0. Post-implementation review (docs/evidence/codex_structural_dead_diff_review_2026-09-05.md) adds: fail-closed on unreadable gaps, CHECK_TOKEN=MATCH required for the PM fill source, half-open gap overlap. No operator-reserved control is set.

## 5. Risks and refusals

- **Refuse** counting paper/shadow/archive rows as fills or as covered days.
- **Refuse** counting an outage day as covered (gap ∩ afternoon, or zero afternoon span).
- **Refuse** changing the 15 threshold, adding ε, or Wilson-on-take-rate.
- **Refuse** KILL vocabulary on `status != REGISTERED`.
- **Refuse** deriving `filled_takes` from scored/settled `len(rows)` (false KILL on an unsettled Take).
- **Refuse** live gateway census calls; residual process-dead≡never-listed stays fail-closed.
- **Refuse** applying this pin to Kalshi in this change.
- Risk: `covers()` without `resolved_gaps_by_seq` would zero the denominator after the first reconnect — use the helper.
- Risk: v1 already consumes this JSON; step 1 must keep v1 goldens (`test_live_family_tally_structural_dead.py`, `test_live_tally_deploy.py`).

Read-only: propose, do not edit.
