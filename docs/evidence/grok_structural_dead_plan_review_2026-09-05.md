# Grok adversarial review — STRUCTURAL_DEAD_RULE_2026-09-05 plan

Run: run-mtog7sh8-4g7ojg (read-only, fresh session). Plan commit 8f76ecc.

**Verdict: APPROVE-WITH-AMENDMENTS**

The hole is real (`main()` never passes counts; empty looks print CONTINUE). Additive KILL on the shared 14:15 JSON is the right shape. Do not implement until the render/terminal_look dual-path, the six-key JSON pin, and the kalshi wrapper gate are amended.

---

### Findings

**1. [CRITICAL] Pre-loop `verdict="KILL"` is invisible at `n < look_step` because render keys off `looks`, not `tally.verdict`.**
Evidence: `build_family_tally_v2` init `verdict = "CONTINUE"` then `range(look_step, …)` at `family_tally_v2.py:511-514` (empty at n=0). `render_markdown_v2:852-872` — SHADOW if `status != "REGISTERED"`, else `**{last.verdict}**` if `tally.looks`, else hardcoded `**CONTINUE** -- fewer than one completed look`. Structural line only when `not evaluable` (`:875-879`). Step 2 RED (`render has **KILL**`) therefore fails against the plan’s Step 3 design.
**Amendment:** On REGISTERED, headline from `tally.verdict`. If `structural_fired` and `looks==()`, print `**KILL**` plus an evaluable structural-dead line. Never treat empty looks as CONTINUE when the pin fired. Keep the DRAFT SHADOW branch first (`:852-858`).

**2. [HIGH] Dual path: `look_verdict` sees `structural_fired`; `terminal_look` does not; pre-loop KILL can be overwritten.**
Evidence: `look_verdict` `current_rung_hold_v2.py:184-209` KILL on `structural_fired`. `terminal_look:221-248` has no such arg; SURVIVE if `S >= b_eff AND pnl>0 AND not cell_dead`. Loop at `family_tally_v2.py:528-545` calls `terminal_look` on any terminal scheduled look and assigns `verdict`. Spec §4: structural-dead is a **separate** KILL, never substituted by the clock. Latent today only if `filled_takes==0` while `n >= look_step`; v1 refuses `filled_takes < len(rows)` (`live_family_tally.py:281-286`) but v2 does not.
**Amendment:** If `structural_fired` and REGISTERED: set KILL, **skip** the look loop (or re-assert after it). Pass `structural_fired` into `terminal_look` and force KILL. Copy v1’s `filled_takes >= n_scored` refuse into `build_family_tally_v2` with a RED test. Do not “keep look_verdict injection” as a second live authority.

**3. [HIGH] Step 1 `outage_excluded_days` breaks the v1 JSON six-key golden the plan did not name.**
Evidence: `_write_output_json` six keys at `structural_dead_stop.py:243-250`. Pin: `tests/unit/test_structural_dead_stop_cli.py:160-197` `set(payload) == {count, depth_root_present, fetch_end, fetch_start, manifest_sha256, stations}`. Plan risk names `test_live_family_tally_structural_dead.py` / `test_live_tally_deploy.py` instead. Wrapper sed (`live-tally-run.sh:62-70`, `score-live-trials-run.sh:84-90`) tolerates extra keys; the CLI test does not. Gate says do not weaken `test_structural_dead_stop.py` and omits the CLI pin.
**Amendment:** Either keep JSON six-key (outages only in the 14:15 log / v2 markdown) **or** change the CLI test to “superset, `count`/`fetch_start` sed-stable, indent-2 sort_keys”. Do not retouch v1 extraction. Do not weaken the 15-floor or live-tally structural goldens.

**4. [HIGH] Generic 15:30 wrapper would attach the PM pin to `kalshi_crh_v1`.**
Evidence: `family-tally-v2-run.sh:27,81-85` takes `$1` with no structural flags. `kalshi_crh_v1.json` is a valid id (`DRAFT_NOT_REGISTERED`, `d0=2099-01-01`). Step 4 requires same-day JSON + `POLYMARKET_US_EXEC_STATE_DB` + `fetch_start==2026-09-05` with no `FAMILY==pm_us_crh_v2` gate. 14:15 writer always uses `pm_us_crh_v2.json` (`score-live-trials-run.sh:26,67-70`). Kalshi would inherit PM coverage and PM fill-source.
**Amendment:** Pass `--covered-listed-station-days` / `--fill-source` / `--fill-since-climate-day` only when `$FAMILY = pm_us_crh_v2`. Other ids keep today’s argv. Copy v1 `exec_state_db_path --check` on the PM path.

**5. [MED] listed≡captured is not actually closed on the catalog path; fail-closed delay-KILL remains.**
Evidence: `discover_station_days` `ma_prelock_winner_ask_study.py:547-560` = captured `tc-temp-{city}high-{day}-` dirs. `covered_listed_station_days:141-155` documents recorder-down ≡ never-listed. Step 1 RED injects 15 listed tuples (fixture c at the function). `count_covered_listed_station_days_from_catalog:185-187` still dirs-only; no union with gap-implied `(station, day)`. Target def “captured **or** QuoteTapeGap ⇒ listed” is not a build-order line. Window∩gap ⇒ not covered is **stricter** than spec span≥30 (`v2 §9`, ratification (1)(f)) — delays KILL, does not manufacture one.
**Amendment:** If fixture (c) is catalog-level, union `resolved_gaps_by_seq` instrument-ids into listed, then mark those days not-covered. If not, drop catalog (c) and pin residual: process-dead with neither dirs nor gap rows delays KILL. Consume `load_partitioned_quote_tape_gaps` / `resolved_gaps_by_seq`; never raw `covers()` on open rows (`tape_records.py:158-164,513-549`).

**6. [MED] Hours: 9.5h is not credible once the missing interactions are in the plan.**
Step 1 3.0h omits the six-key contract + catalog gap load + instrument_id→(station,day). Step 3 1.5h is a 5-line `verdict=` patch that does not print KILL (finding 1–2). Step 2/4/5 (2.0+2.0+1.0) are fine if 4 is a copy of `live-tally-run.sh:47-80` plus the family-id gate.
**Amendment:** Rebudget Step 1 → 4.0h, Step 3 → 3.0h (render + skip-loop + `terminal_look` + `filled_takes>=n_scored`). Total ~12h. Do not collapse 14:15 counter into 15:30; the split is already correct (`breezy-score-live-trials.timer` 14:15, `breezy-live-tally.timer` 14:30, `breezy-pm-crh-v2-tally.timer` 15:30).

**7. [LOW] R2 cite is wrong; empty unmarked store is indistinguishable from a fresh live node.**
Plan `family_tally_v2.py:291-293` is the qty-guard raise, not R2. R2 is `:468-478` / field `:245-250`. Empty paper dir with no sidecar is admitted as n=0; Step 5 only refuses a `paper_replay` sidecar. Operational default store is live (`BREEZY_SCORED_TRIALS_DIR`).
**Amendment:** Fix the cite. Step 5: marked `paper_replay` refused **before** `structural_dead()`; empty unmarked stays R2. `count_filled_takes` live prefix (`fill_time_count.py:113-115`, `_LIVE_TRIAL_ID_PREFIX` `live_family_tally.py:83`) cannot count `paper_replay/current_rung_hold/trial/` keys. Do not derive `filled_takes` from `len(scored)`.

---

### Plan claims verified

| Claim | Result |
|---|---|
| `structural_dead` 100–121; 15 imported, no second literal | **TRUE** (`structural_dead_stop.py:78,100-121`; `test_structural_dead_stop.py:95-101`) |
| listed ≡ captured dirs `:141-155` / `discover_station_days:547-560` | **TRUE** |
| `QuoteTapeGap` `:51`; log `:1806`; publish `:1846`; `covers()` open = all-future; must use `resolved_gaps_by_seq` | **TRUE** (`tape_records.py:51,158-164,513-549`; `data.py:1806,1846`) |
| `--family-manifest` ⇒ `fetch_start=d0` `:266-278`; end `ASOS_FETCH_END` | **TRUE** (`:277,300`; `ma_prelock:185`) |
| 14:15 `score-live-trials-run.sh:67-70` writes `covered_listed_station_days_<date>.json` | **TRUE** |
| v1 live KILL wired `live_family_tally.py:238-340` + CLI `:455-470` + `live-tally-run.sh:92-98` | **TRUE** |
| `build_family_tally_v2` **can** call `structural_dead` `:496-503`; `main():939-946` never passes counts | **TRUE** |
| `family-tally-v2-run.sh:81-85` passes neither JSON nor fill-source | **TRUE** |
| `structural_fired` only into `look_verdict` inside `range(look_step,…)` `:514-570` | **TRUE** |
| `terminal_look:221-248` ignores `structural_fired` | **TRUE** |
| `render_markdown_v2:861-872` prints CONTINUE when `looks==()` | **TRUE** |
| REGISTERED gate `:852-858` shadows DRAFT | **TRUE** |
| `assert_family_only:47-74`; `_assert_live_provenance:325-348` | **TRUE** |
| R2 at `family_tally_v2.py:291-293` | **FALSE** (qty guard; R2 is `:468-478`) |
| No `test_family_tally_v2*` names structural | **TRUE** (suite exists; truncation test pins n&lt;look_step ⇒ `verdict=="CONTINUE"` at `test_family_tally_v2_truncation.py:291-300`) |
| Manifest `REGISTERED`, `d0_climate_day=2026-09-05` | **TRUE** |
| v2 §9 / v1 §5:105–106 / ratification (1)(f) wording; §12 rejects extra ε / Wilson-on-take-rate | **TRUE** |
| Paper rows increment `filled_takes` via live prefix | **FALSE** (`fill_time_count.py:113-115`) |
| Step 1 extra JSON key is v1-safe without a test change | **FALSE** (`test_structural_dead_stop_cli.py:160-197`) |

---

### Q2 (verdict precedence)

KILL-before-loop is the right *builder* move at n=0 (look_step=10; `scheduled_ns` empty), but it does not survive `render_markdown_v2`. REGISTERED + empty looks still prints hardcoded `**CONTINUE**`; DRAFT still prints SHADOW and that gate must stay first so a DRAFT never emits KILL vocabulary. `terminal_look` is a second authority: a later truncation/I_MAX/LOSS_STOP look overwrites pre-loop KILL because it never sees `structural_fired`; v2 also lacks v1’s `filled_takes >= n_scored` refuse that makes n≥10 ∧ filled_takes==0 a wiring defect. v1 `build_live_family_tally` only reads `count`/`fetch_start` from the same JSON; extra keys do not break wrapper sed, but they **do** break the six-key CLI golden — v1’s Python golden path is otherwise untouched. Paper/archive rows cannot increment `filled_takes` (`startswith` live prefix). A `paper_replay` sidecar is refused before `structural_dead()`. Residual false-KILL paths: empty unmarked store (R2) plus live fill-source of 0, or a non-live sqlite passed as `--fill-source` (readable ⇒ 0, not `None`). Copy v1 node-env pre-flight; do not count `len(scored)`.

### Q6 (hours)

3.0+2.0+1.5+2.0+1.0 is only credible if Step 3 is a one-line `verdict=` and Step 1 does not touch JSON shape — both false. Budget 4.0h for gap join + listed-union-or-documented-residual + six-key contract, and 3.0h for render headline + skip-loop/`terminal_look` + `filled_takes>=n` refuse. Keep 14:15 writer / 14:30 v1 / 15:30 v2; do not merge ticks.
