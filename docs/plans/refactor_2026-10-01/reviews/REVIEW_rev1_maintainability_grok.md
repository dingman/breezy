I'll review the plan against the repo only: read it in full, then check the pins, importers, and layer contract it relies on. No files will be changed.The plan is loaded. Next I’ll check the pins, layer contract, and the importers the dead-code and move steps depend on.## Maintainability review — PLAN_Rev1

Verdict: **APPROVE-WITH-CHANGES**. The non-substitution stance and the Phase 0 pin work are sound. Do not execute R1.1 as sited, R1.2, R1.3, R2.3’s preferred target, R2.4, or the §4.4 “under 800” targets. R3.5 stays deferred.

### A. Complexity / YAGNI

| Step | Finding | Tag |
|---|---|---|
| **R0.1** | Comment-only, but tagged **LIVE** because it edits `app/trade.py` and `exec/client.py`. A 25-minute live-window gate for comments is not worth it. Fold the live-file comments into R3.1 / any real edit of those files. | CONFIRMED plan §R0.1; files exist (`trade.py` 1099 lines, `client.py` 5957) |
| **R0.3, R0.4, R0.6, R0.7** | Each is a small test or one config line, and each is specified to take a full gate. Merge into **one** test/config commit. | CONFIRMED plan §3.2 global gate |
| **R0.5** | Eleven characterization tests. Only CT-1, CT-2, CT-4, CT-7, CT-8 unblock an R-step. CT-3, CT-5, CT-6, CT-10, CT-11 do not. CT-9 is attached to the wrong step (below). Split; do not block Phase 1 on the optional six. | CONFIRMED plan lines 314, 481–484 vs C3 at 174 |
| **R0.6** | Keep, inside the merged Phase 0 commit. It does **not** catch “import module A, which imports dead strategies at import time.” | CONFIRMED `run_weather_strategy_backtests.py:244-259` are column-0 imports |
| **R0.7** | The marker alone changes nothing until Rev 2 marks files. `slow` really cannot be reused (`pyproject.toml:56`). Legal (addopts pin is a substring, not a marker-list equality). Drop until the durations table exists, or land it only as part of the merged Phase 0 commit. | CONFIRMED `test_test_safety_tooling_config.py:43-46`; `test_probe_containment.py:583-585` |
| **R1.1** | About 30 lines. The four protocols are duplicated **on purpose** so `submit_intent` does not import a Nautilus path (`submit_intent.py:43-48`). `breezy.persistence` is not an import-free package: `__init__.py:8` imports `catalog`, and `catalog.py:198` imports Nautilus. `import breezy.persistence.state_store` runs that `__init__` first. `domain/__init__.py:16-53` has the same side effect. A new top-level package would edit the exhaustive layer list. **Drop.** | CONFIRMED those lines; package-init semantics |
| **R1.2** | New parameterized helper (`_on_task_death` hook) on the live FQ feed, to unify copies the plan itself says are **not** identical (`nws_observation_actor` fail-closed). If BC-4 deletes `nbm_forecast_actor`, the remaining pair is the non-identical one. **Drop.** | CONFIRMED plan lines 346–349; actor is live via `app/trade.py` per plan |
| **R1.3** | The three `Node` protocols are different surfaces, not near-copies. `cli.py:90-97` is `build/run/dispose`. `quote_tape_cli.py:123-132` adds `add_data_client_factory`. `trade_cli.py:253-289` adds `kernel`, `trader`, `add_exec_client_factory`, and the comment says a structural kernel Protocol fails mypy. `runtime` is in the mypy **CLEAN** set (`test_mypy_ratchet.py:299`), which may not be relaxed by raising a ceiling. **Drop.** | CONFIRMED those lines |
| **R1.4** | Real split (probe is `catalog.py:961-1202` of a 1202-line file). Keep. Re-export is justified because `__init__.py:8-29` imports those names from `catalog`. | CONFIRMED `wc` 1202; `__init__.py:8` |
| **R1.5** | One debt row, same-commit pin edit. Worth doing. Not an abstraction. | CONFIRMED `pyproject.toml:105`; test set `test_test_safety_tooling_config.py:87-92` |
| **R1.6** | No src importer sits below `persistence` (`load_partitioned_quote_tape_gaps` callers are `scripts/analysis/structural_dead_stop.py` and tests). The drop condition is not met. The module imports Nautilus directly (`quote_tape_gaps.py:15-17`), so it **cannot** move to `breezy.analysis`. Only `adapters` or `runtime` is legal. Name that destination or drop. | CONFIRMED codegraph callers; `quote_tape_gaps.py:15-19` |
| **R2.1** | A parity test, script unedited. Keep. Do not make src the source of truth in this plan; that is a ruling change (P-13). | CONFIRMED plan lines 397–402 |
| **R2.4** | Public aliases for private names, and `decision.py` is **LIVE**, to serve a tripwire R0.6 already covers. Plan already says drop. **Drop.** | CONFIRMED plan lines 430–435 |
| **R3.1** | “−40 to −80 LOC” does not decompose a 1099-line module. Keep only if the halt-latch duplication is a pure extract with byte-stable boot logs. Do not sell it as a file split. | CONFIRMED `wc` 1099; plan line 444 |
| **R3.3** | Helpers in the **same** file do not shrink 2441 lines. The four named functions are 635 lines; even a sibling move leaves ~1806. | CONFIRMED `wc` 2441; plan lines 460–462 |
| **R3.5** | Not a pure move. `_resolve_ambiguous_intents` is a bound method. A sibling function that replaces `self` changes callee shapes on `EXEC_RESOLVER_PERMITTED_CALLEES` (`test_execution_egress_firewall_guard.py:2118+`). Default defer is right. | CONFIRMED plan line 475 vs method-shaped allowlist |
| **R3.6** | Health extraction is a reasonable late move. It is **not** “domain boilerplate,” and it does not need CT-9. | CONFIRMED plan C3 line 174 vs R3.6 lines 481–484 |

### B. Sequencing and rollback

Recommended order matches the stated dependencies **except** R1.1 is sequenced as if `persistence` were import-free, R1.2 is after R0.5 for a step that should be dropped, and R3.6’s CT-9 dependency is a label collision. R2.3-before-BC-3 is right in intent and false in effect (section D).

`git revert` of one commit is clean only when every pin that commit changes is inside that commit. These are the pins:

| Step | Must touch in the **same** commit | Revert |
|---|---|---|
| R0.1–R0.6 | No `pyproject` pin. R0.1 must not touch `archive_table.py` (mypy CLEAN carve-out, `test_mypy_ratchet.py:302-305`). P1 scans rebinding, not comments (`test_cage_rule_constants_are_pinned.py:1084-1109`). | Clean |
| R0.7 | `pyproject.toml` `markers` only. **Do not** edit `addopts`. Pin is the substring at `test_probe_containment.py:585`, not marker-list equality. | Clean |
| R1.5, R1.6 | Delete exactly one string from `pyproject.toml:100-108` **and** from the set at `test_test_safety_tooling_config.py:87-92`. Order them; each commit’s set must match that commit’s toml. | Clean **if** one commit. Split commits do not revert independently |
| R1.4 | Keep `tests/unit/test_archive_import_contract.py:15` and `:49-56` planting an import **onto** `persistence/catalog.py`. A re-export does not retarget `monkeypatch` of `breezy.persistence.catalog._…`. | Clean if the plant path is unchanged |
| R2.2, any move out of `scripts/analysis` | `CEILINGS` are exact and **fall** is failure: `scripts/analysis: 364`, `src/breezy/analysis: 13` (`test_mypy_ratchet.py:313-323`). `assess_ratchet` tells you to lower the ceiling (`test_mypy_ratchet.py:161-162`). A following “re-baseline” commit means the move commit is red, and rollback is **two** reverts in order. Put the count change in the same commit as the move, with before/after in the message. Do not “raise” a CLEAN package (`adapters`, `ingest`, `persistence`, `runtime`, `strategy` are CLEAN, lines 283-301). | **Not** one `git revert` under the plan as written |
| R3.5 | N2 equality list `test_execution_egress_firewall_guard.py:738-772` (one new `E0` row). `EXEC_ASYNC_LIFECYCLE_MODULES` line 1788 (today only `exec/client.py`) because a new async module fails E0-INERT at `:2542-2549`. Resolver scan already runs per module (`:2569` inside `find_exec_inertness_violations`). **There is no X3 file allowlist to widen**; X3 is a vocabulary scan. Adding an X3 exemption would relax L-12. | Clean if those sets move with the code |
| BC-5 | Not only `pyproject.toml:96` and test line 133. The layers list is **equality-pinned** at `test_test_safety_tooling_config.py:68-86` (`"features \| settlement"`), and `breezy.features` is also in the forbidden `source_modules` at `pyproject.toml:158-161` and test `:124-136`. `features/__init__.py` is empty (0 bytes). | Clean if all three sites move together |
| Units / docs | R2.2 says unit files stay. `breezy-replay-daily.service:60` and `breezy-score-live-trials.service` pin **script paths**. Revert is clean only while those paths still exist. R0.2’s L-36 anchor edit does not unblock later steps. | Clean |

`test_archive_import_contract.py:46-56` rewrites `catalog.py` on disk during the gate and restores it in `finally`. That is why the gate must not run in `/home/jon/breezy` (plan C8). It is not itself a revert hazard.

### C. Dead code

**Five shells.** `wc` matches the plan: the five packages sum to **5637**, plus `forecast_edge.py` 224, `resting_ladder.py` 392, `strike_ladder.py` 318 = **6571**. No `app/` importer. Production import side effect is `scripts/analysis/run_weather_strategy_backtests.py:244-259` (module scope). Also:

- `current_rung_hold_paper_replay.py:69-77` imports **seven** names from that module, not four.
- `whole_tape_paper_replay.py:43-47` imports `DEFAULT_WEATHER_CATALOG_ROOT`, `WEATHER_VENUE`, `TapeInstrument`.
- `replay_sufficiency_census.py:94` imports `WEATHER_VENUE, _capture_instruments_by_id` (the plan’s pair).
- `weather_strategy_backtest_lib.py:42` imports `cli_settlement_print_lock` **inside a function** (indented). Importing the lib does not load the shell; calling that function does. The plan does not name this file.

**NBS chain.** No src or scripts importer of `NbmForecastActor`, `nbm_forecast_parse`, `IemMosFallbackTransport`, `breezy.ingest.archive_records`, or `breezy.domain.archived_selection` beyond tests and comments. LOC 402+276+235+95+83 = **1091**. CONFIRMED. Missed pins if deleted:

- Forbidden-contract name `breezy.ingest.archive_records` at `pyproject.toml:145` and `test_archive_import_contract.py:74`. Import-linter requires a named module to exist (`pyproject.toml:193-194`).
- `IEM_HOST_ALLOWED_MODULES` is exactly `{src/breezy/ingest/iem_mos_fallback_transport.py}` at `test_archive_import_contract.py:84-86`.
- More than “3 test files”: `test_nbm_forecast_actor.py`, `test_nbm_forecast_parse.py`, `test_iem_mos_fallback_transport.py`, `test_ingest_archive_records.py`, `test_domain_archived_selection.py`, plus the string in `test_nbp_shadow_parity_contract.py:51`.

**R2.3 does not decouple the nightly.** `breezy-replay-daily.service:11-12,60` runs `replay-daily-run.sh` → `replay_daily_runner.py`, which drives `current_rung_hold_paper_replay.py`. That script still imports the backtest module after the four-name extract, so the five shells still load. Census can be switched; the timer is not the census.

**Rulings / lessons.** No ruling found that forbids deleting the five strategy packages. `L-9` (`LESSONS.md:449`) says stop designing lock strategies; it is not a deletion authorization. `RULING_R5_prereg_v1_tally_2026-09-24.md:30` says leave `scripts/analysis/live_family_tally.py` **in the repo, unedited in logic**. Archiving or moving that file violates the ruling; “never delete” is weaker than what was ruled. `RULING_A1_…:300` says do not delete the `pm_us_crh_v4` registration, not these shells. `PROGRESS.md:41-42` binds PREREG **semantic** changes to a ruling; a pure deletion is not that, but BC-3 must not edit tally math.

### D. Scripts → src

Layer order is `app > analysis > strategy > runtime > …` (`pyproject.toml:77-98`). `app` (and strategy, runtime, adapters, ingest, persistence, …) may not import `breezy.analysis` (`pyproject.toml:156-163`; test `:122-137`, indirect forbidden). Scripts are outside that source list, so a script may import `breezy.analysis`.

**Preferred `breezy.analysis.tape_instruments` is illegal.** `TapeInstrument` fields are Nautilus types (`run_weather_strategy_backtests.py:534-538`): `BinaryOption`, `OrderBookDepth10`, `QuoteTick`, `InstrumentClose`, and the file imports them at `:193-200`. The analysis contract forbids a direct `nautilus_trader` import (`pyproject.toml:165-177`; test `:143-147`). The **fallback** — a new `scripts/analysis` module — is the one that typechecks against the layer contract. Same ban if R2.2’s move includes `catalog.instruments()` (`score_live_trials.py:1213`). The named functions start at `:376`, `:468`, `:557`; the catalog walk is a different function and must stay out of `breezy.analysis`. HYPOTHESIS: `_admit_fill` / `read_filled_trials_state_db` / `fill_time_count.py` are sqlite-only. Not proven from the signatures alone.

**Citability.** R2.1 correctly refuses to edit a ruling-cited generator. R2.2 still rewrites `score_live_trials.py`, which moves every line a ruling cites. “Path unchanged” is not “byte-identical and citable.” `RULING_R5:30` also requires `live_family_tally.py` unedited, which BC-6’s archive would break.

**Byte-identical nightly output is not testable as stated.** The replay unit appends one `replay_results.jsonl` row per invocation (`breezy-replay-daily.service:11-12`), for one station-day, under `~/.local/share/breezy/derived/replay/`. That is not a frozen file. `score_live_trials` writes a dated marker `score_live_trials_ok_<date>` (`deploy/systemd/README.md:957,1090`). A parquet/JSONL tree that embeds wall time, `score_seq`, or a date in the filename will not compare equal. A real check is: frozen inputs, frozen `--as-of`, compare the **semantic** payload after stripping marker names and writer metadata. The plan does not say that.

### E. Success criteria

Measurable and fair: `ignore_imports` 4→3 via the set equality at test `:87-92`; unmarked contract modules 10→0; fork tests 4→1; “0 new skips”; no private asserts in new tests.

Not consistent with the evidence:

- **`catalog.py` under 800.** 1202 − ~241 = **~961**. CONFIRMED.
- **`app/trade.py` under 800.** File is **1099**. R3.1 removes 40–80 lines, not 300. CONFIRMED.
- **`quote_tape_ingest_cli.py` under 800.** File is **2441**. Same-module helpers remove nothing; moving the four functions leaves **~1806**. CONFIRMED.
- **Full gate ≤ baseline after Phases 0–3.** R0.5 and R0.6 add work. The −5–15% after BC-3 is already labeled HYPOTHESIS. The “≤ baseline” line is not.
- **T1 ≤ 5 min.** No durations (plan §4.6 is empty). Vanity until Rev 2.
- **“~250–300 duplicate LOC” for R1.1+R1.2+R1.3.** R1.1 is ~30. The rest is an undiffed estimate, and two of the three steps should be dropped.
- **Private-assert “−15 sites”** against a baseline of 741 lines. A site count, not a reduction of the metric.

Shell LOC 5637 / 6571 and NBS 1091 match `wc`. Those figures are fine.

### F. Required revisions

1. **BLOCKER.** Drop R1.3. The protocols differ, and a mypy failure cannot be re-baselined out of a CLEAN package (`trade_cli.py:253-289`, `test_mypy_ratchet.py:299`).
2. **BLOCKER.** Do not put `StateStore` in `breezy.persistence` or `breezy.domain`. Both package inits import Nautilus (`persistence/__init__.py:8`, `catalog.py:198`, `domain/__init__.py:16-53`). Drop R1.1.
3. **BLOCKER.** R2.3 preferred target violates the analysis/Nautilus ban (`TapeInstrument` at `run_weather_strategy_backtests.py:534-538`, contract at `pyproject.toml:165-177`). Use a `scripts/analysis` module. Move **every** name that `current_rung_hold_paper_replay.py:69-77` and `whole_tape_paper_replay.py:43-47` import, or make the five strategy imports lazy. Until paper replay can import the new module and not the old one, BC-3 still breaks `breezy-replay-daily`.
4. **BLOCKER.** R2.2 must not move `catalog.instruments()` (`score_live_trials.py:1213`) into `breezy.analysis`. Re-baseline `scripts/analysis: 364` and `src/breezy/analysis: 13` in the **same** commit as the move.
5. **BLOCKER.** BC-6 may not move or edit `scripts/analysis/live_family_tally.py` (`RULING_R5:30`).
6. **MAJOR.** Drop R1.2 and R2.4.
7. **MAJOR.** Merge R0.3+R0.4+R0.6+R0.7. Split R0.5. Detach CT-9 from R3.6; fix the C3 label collision.
8. **MAJOR.** R3.5: if ever done, same-commit edit of the N2 list (`:738-772`) and `EXEC_ASYNC_LIFECYCLE_MODULES` (`:1788`). Do not add an X3 row. Treat callee-shape changes as a scan escape (L-46), not a pure move.
9. **MAJOR.** BC-4 must edit the archive forbidden row (`pyproject.toml:145`, test `:74`), `IEM_HOST_ALLOWED_MODULES` (`test_archive_import_contract.py:84-86`), and the extra test files in section C. BC-5 must edit the layers equality (`test_test_safety_tooling_config.py:68-86`) and the forbidden `source_modules` (`pyproject.toml:158-161`), not only line 133.
10. **MAJOR.** Replace §4.4 “module under 800” and “gate ≤ baseline” with deltas this plan actually produces. Define byte-identity as a stripped payload on frozen `--as-of` inputs.
11. **MINOR.** Keep R0.1’s live-file comments for the commit that already edits those files. R0.7 waits for §4.6 unless it rides the merged Phase 0 commit. R1.6: destination is `adapters` or `runtime`, or drop. R2.1 stays a pin, not a merge.
