S0 bootstrap-cost benchmark, 2026-11-02 (synthetic only; no J2/J3 outcome read)
Machine: Intel Core i7-11700K @ 3.60GHz, 16 logical CPUs; Linux 7.0.0-38-generic x86_64, glibc 2.43.
Runtime: /home/jon/breezy/.venv/bin/python, Python 3.13.13; PYTHONPATH=/home/jon/breezy/.claude/worktrees/gap1-kill/src.
One serial measured set: 120,000 (station, day, p_arm, p_m0, outcome) events, 900 station-day clusters, B=1000, seed=20260929.
Fixture: 40,000 rows x 3 rungs; cluster=row%900, station=S{cluster%5}, day=2025-01-01 + cluster//5 days (180 dates).
Random(seed): per row draw 3 U(0.1,1) M0 weights, perturb each by U(-0.1,0.1) with floor .01 for arm; normalize separately; one arm-categorical winning rung.
Statistic per draw: resolution_difference(p_arm, p_m0, outcomes, bin_by_edges(RELIABILITY_BUCKET_EDGES)); recompute both full decompositions.
Calls: nbp_calibration.cluster_bootstrap_draws(..., cluster_key=(station,day), iterations=1000, seed=20260929), then percentile_interval(draws, alpha=0.05/6).
Bootstrap elapsed: 164.3784188129939 s; interval: 0.000012219883501529694 s; total: 164.3784321891144 s; process CPU: 164.358423159 s.
Fixture construction/imports excluded; measured total includes resampling, statistic, draw sort, interval, and progress prints every 100 draws.
Synthetic CI: [0.0009138470848075418, 0.001604481311952885]; timing fixture only, no skill evidence.
Projection: total * (10000/1000) * 6 * 2 / 3600 = 5.47928107297048 hours for B=10000.
Resulting precommitted B: 5000 because projection >4 hours; projected 2.73964053648524 hours at B=5000; never below 2000.
Projection assumes this event count, serial execution and similar cost for both clusterings; it is not a J3 fitting-runtime measurement or guarantee.
Source refs: nbp_calibration.py:1713-1747,2025; brier_decomposition.py:232-268. No scoring_core import occurred.
Frozen-blob schema: check_frozen_blob (scripts/analysis/prereg_precommit_check.py:323-368) requires only top-level frozen_sha (40 lowercase hex); no required content_sha256 key.
It checks an existing ancestor commit and canonical equality of the entire JSON object except frozen_sha (sorted keys, compact separators, ASCII).
check_not_refrozen (scripts/analysis/multisource_blend_pin_guards.py:185-229) uses top-level frozen_sha and exact file bytes; full non-shallow history must contain <=1 distinct non-UNFROZEN state.
Conflict: required TODO-S0b is itself a non-UNFROZEN stamp, so this draft is not freeze-ready; an in-place later stamp would fail the history guard.
S0b must resolve the freeze lifecycle using a separately approved new-version path; no guard changes, history rewriting or silent compatibility claim.
F13 header content_sha256 is canonical SHA-256 excluding frozen_sha, not the whole-file hash; its existing two freeze guards passed.
K_cum: no seed or 09-30 inclusion evidence in docs/core/PROGRESS.md; before/after TODO-S0b. Conservatively count 09-30 unless proven already seeded.
Prior sigma uses code X and code z constants rounded to six decimals: 0.0152*sqrt(592)/(1.959964+0.841621)=0.13200811749139565; adjusted floor=914.
OPEN_ITEMS: frozen_sha (TODO-S0b, including freeze-history compatibility); k_cum.before (TODO-S0b, reconcile 09-30); k_cum.after (TODO-S0b, derive before+added).
