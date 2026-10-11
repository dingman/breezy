VERDICT: READY
SCORE: 90/100

I ran no tests. This was a plan review limited to reads of code, git and logs. I found no BLOCKER or HIGH. The two MED and two LOW items below can be folded in at WP0 and WP2 without another round.

**r2 findings N1–N8**

| r2 ID | Status | Evidence |
|---|---|---|
| N1 | Resolved | Pin rule is per boot, label `PIN=INFERRED`, and the manifest and artefact blobs at the chosen commit are checked against the logged shas. I confirmed `60290e9d` (committer 2026-10-01T13:39:52Z) holds a manifest blob with sha256 `8e1217fd…` and that the artefact file is `9c0b6d6e…`. |
| N2 | Resolved | The HEAD-blob sha plus a `git status --porcelain` clean-path check, the ancestor check, a post-hoc verifier (#39), a re-freeze rule (#38), and no commit-message sha. |
| N3 | Resolved | Labels corrected. |
| N4 | Resolved | Truth is the catalog via `NwsCliFinal`, with a clipping wrapper and a `tmax_f`-free projection (#33, #34). |
| N5 | Resolved | RED is declared as `AssertionError` or `NotImplementedError`. The typo is fixed and #45 uses `tracemalloc` or a lazy generator. The tests I listed as missing are now present (#19, #21, #22, #26, #29, #30, #35, #6, #7, #15). |
| N6 | Resolved | `combine_station_day` is dropped, with the reason stated. |
| N7 | Resolved | The raise is at `decision_link.py:213-214`. The `trade_id`, `recalibration` and `epoch_class` inputs are named. |
| N8 | Resolved | The full path to `forecast_state` is given. |

**Findings**

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| R3-1 | MED | The pin path set is narrower than the decision path's import closure. P7 says only `4ac87414` falls between fill boots and that it touched "`forecast_state.py` +4 lines". The commit also changed `normalize/climate_day.py` (+26) and `ladder_ev/forecast_subscriber.py`. `f2e91fe4` (10-04T09:48Z, the `ladder_ev` package facade) falls in the window and is not listed. Blob corroboration covers only the manifest and artefact. | `git show 4ac87414 --stat`; `git log` on `ladder_ev` and `nbm_quantile_actor.py` | Widen the git-log path set to `normalize/climate_day.py`, `strategy/ladder_ev/`, `ingest/nbm_quantile_actor.py` and `strategy/forecast_quantile_ladder/strategy.py`. Restate P7. This does not change the INFERRED label or the 23-of-25 STOP, so the plan stays sound. |
| R3-2 | MED | T-LOC is marked TESTABLE at 7 clusters with a minimum p of 0.0156, tested against the lenient 0.02 threshold. Under Holm over two tests, the step-1 threshold is 0.01. T-LOC can therefore reject only if T-SPREAD already rejected at p ≤ 0.01. The VARIANCE clause "at least one TESTABLE secondary" can then be satisfied by T-LOC alone, which cannot reject on its own. | Plan §2, S0-I; `nbp_calibration.holm_correction` | In S0-I, mark a member as "TESTABLE-conditional" when its minimum p exceeds α/k. Require an unconditionally testable secondary for the VARIANCE clause. |
| R3-3 | LOW | The pin resolver is implementable: `git log --format='%H %cI'` over the paths, then a Python filter on committer time, then `git show <c>:<path>` piped to sha256. Committer times are skewed by rebases (`60290e9d` has author time 03:20Z but committer time 13:39Z). `git log --until` and `rev-list` can stop early on such skew. | `git log` output above | Specify "filter in Python, not `--until`". Add a skewed-date fixture to #44. |
| R3-4 | LOW | `decision_link.py:215` is the `if fill.trade_id is None:` line. The `BridgeUnmatched("no_trade_id")` return is at `:216`. | `decision_link.py:215-216` | Fix the cite. |

**Direct-only import pin: confirmed.** X1 scans `tests/` only (`TEST_SCAN_ROOTS`). `_imports_exec_package` checks per-file AST imports (`:1168-1185`), not transitive ones. X2 scans `src` and `scripts` for banned constructs, not for exec imports. `scripts/analysis/score_live_trials.py:102` already imports `exec.client` directly. The new `scripts/` modules, which import only `fill_source` and `decision_link`, will not trip the exec-import pin. The plan's WIDENED fallback covers the case where they do.

**The 49 RED tests.** They fail for the right reason: the stubs raise `NotImplementedError`, which the plan counts as RED, and `ImportError` is excluded. They are feasible. Temporary git repos can set `GIT_COMMITTER_DATE` for #37 to #39 and #44. The fixtures in #9 and #49 are real instrument-id slugs via `bucket_facts_from_instrument_id`. Positive controls exist (#6, #26, #42, #36), and the focused gate includes the firewall, exec-import, `test_autonomy_*` and `lint-imports` guards.

**Premises checked**
- `epoch.py:98` `fill_epoch_class`: CONFIRMED.
- `decision_link` `:213-214` and `:243` (`raw_yes`): CONFIRMED. `:215` is only the `if` (R3-4).
- `probability.py:77` `artefact_p_raw`: CONFIRMED. It returns `p` only when the recalibration token is `RECALIBRATION_NONE`.
- `fill_source.py:21` imports `exec.client`: CONFIRMED. `decision_link.py:28` does too. `:49` `require_clean` and `:58` `read_durable_fills`: CONFIRMED.
- `settlement_source` `:37-38` Protocol, `NwsCliFinal`: CONFIRMED.
- `persistence/catalog.py:637` `read_climate_day_including_corrections`: CONFIRMED.
- `symbology.py:483-500` `slug_closed_interval`: CONFIRMED. `lt` gives (None, B−1), `gte` gives (A, None), and `gteAltB` gives [A, B].
- `forecast_state` `:88` (TXN `push`), `:245` (quantile `push`), `:310` (`value_at`): CONFIRMED.
- `trade.py:1002-1012` `_record_boot_epoch` and `:1150` call site: CONFIRMED.
- `nbp_calibration.py:273` `DEFAULT_SPLITS`: CONFIRMED.
- P7 git-log commit list and committer times: CONFIRMED. The scope is incomplete (R3-1).

Plan file: `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3.md`