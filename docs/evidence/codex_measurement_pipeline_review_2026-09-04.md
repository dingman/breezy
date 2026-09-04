# Codex adversarial review — live-family measurement pipeline (2026-09-04)

**Provenance.** Independent static, read-only review by Codex (codex-cli 0.130.0,
sandbox read-only, cwd = repo, no pytest, no bot run, no network) of
`scripts/analysis/live_family_tally.py`, `score_live_trials.py`,
`mb_current_rung_edge_study.py`, `current_rung_hold_paper_replay.py`,
`src/breezy/settlement/{trial_scorer,roi_bound}.py`,
`src/breezy/persistence/scored_trial_store.py`, PREREG v1 (binding) and the
PREREG v2 draft. Brief: hunt look-ahead/leakage, survivorship, win labelling,
BCa correctness, the Wilson kill/survive hurdle, live-n contamination, and
missing tests. Coordinator dispositions follow each finding; the coordinator
verified the cited lines exist but did not re-derive every claim.

| # | Sev | Finding (Codex) | Disposition (coordinator) |
|---|---|---|---|
| 1 | HIGH | v1/M_B Wilson hurdle pools asks as `BE(mean ask)`, not `mean(BE_i)` (`mb_current_rung_edge_study.py:727-744`; `live_family_tally.py:46-53,290-303`). Mixed-ask strata overstate the hurdle; kill/survive can flip. | KNOWN, RULED. v1 is binding and unmodified while live; v2 adopts per-row `BE_i` (`grok_v2_score_statistic_ruling_2026-09-04.md`). No v1 change. |
| 2 | HIGH | Wilson `k` counts `held`, not "net P&L after fees > 0" (`trial_scorer.py:186-187`). Diverges only for malformed rows or a fee-model change. | v2 tally REFUSES any row where `held != (pnl > 0)` (fail-closed guard, never relabels); ruling requested from the strategy lead (Q3). v1 unchanged. |
| 3 | HIGH | Fill `qty` accepted but ignored: zero/partial/multi fills score as one full contract (`score_live_trials.py:47-60,161-185`; `trial_scorer.py:81-86`). Real since the venue's `minimumTradeQty` is 0.01 from 06-14 (partial fills of a 1-contract order are possible). | Strategy-lead ruling requested (Q1 v1, Q2 v2) on weighting vs refusal. v2 tally refuses `qty != 1` rows loudly until ruled. v1 rows persist raw and can be re-scored after the ruling; no fills exist yet (n = 0). |
| 4 | MED | Live provenance is a forgeable `trial_id` prefix, not a stored field (`live_family_tally.py:148-164`; store `:53-72`). | v2 keeps prefix + `climate_day ≥ D0`; explicit provenance column proposed to the strategy lead (Q4); store schema is v1-owned and untouched. |
| 5 | MED | M_B denominator is captured-depth survivorship: unlisted/pending/low-coverage station-days never reach n (`mb_…:1138-1155,600-613,670-679`). | KNOWN and disclosed in the study's coverage table; M_B is kill/survive only, never a verdict on ROI. 09-02 VENUE-NEVER-LISTED and 09-03 recorder outage are both visible there. |
| 6 | MED | Equal `score_seq` ties keep the first row (`scored_trial_store.py:104-120`); two racing scorers could hide a corrected settlement. | v2 tally refuses `(trial_id, score_seq)` collisions. Scoring is single-timer today. |
| 7 | LOW | BCa point estimate θ̂ computed but omitted from the rendered BCa line (`roi_bound.py:140-145,201-206`; `live_family_tally.py:439-440`). | v2 tally prints θ̂ with lower bound, n, B, seed. v1 report unchanged. |

**Existing tests Codex found pinning the safe behaviours:** lagged entry at
`t+lag` and first-executable snapshot (`test_mb_current_rung_edge_study.py:220-325`),
live first-snapshot latch (`test_current_rung_hold_strategy.py:288-309`),
entry-ask-from-latch and uncovered-tape refusal (`test_current_rung_hold_paper_replay.py:600-656,974-995`),
BCa exclusion ceiling / n<30 / ratio-of-sums (`test_settlement_roi_bound.py:82-197`),
live-vs-paper prefix refusal (`test_live_family_tally_provenance.py:74-106`),
structural-dead fill count (`test_live_family_tally_structural_dead.py:81-129`).

**Missing tests named:** mixed-ask fixture for `mean(BE_i)` vs `BE(mean ask)`;
a `held=True, pnl<=0` row that must not count as a win; zero/partial/non-1
`qty` refusal; spoofed archive/shadow row with a live-shaped `trial_id`;
equal-`score_seq` collision. The v2 build carries (b)–(e); (a) is v2's
statistic by construction.

**No look-ahead found** in the listed scripts: M_B selects the entry row at
`ts_event >= t + lag`; staleness and first-executable enforcement live in
`decision.py`/`strategy.py` (outside the reviewed set) and are pinned by the
tests above.
