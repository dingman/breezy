# RA-5a — Residual-sidecar family keying: VERIFIED-ISOLATED (2026-09-27)

This is EDGE-5 RA-5a (POST_FORECAST §A-9 clause 3). It takes option (a): the existing partition already keys residual sidecars by family, so there is nothing to build.
- Verified at HEAD a27d965, read-only (Codex), with the coordinator spot-checking the citations marked ✔.

| Check | Evidence | Holds |
|---|---|---|
| trial_id prefix | `settlement/family_barrier.py:75-79` ✔; the scorer receives the manifest prefix at `score_live_trials.py:1803,1813` and filters latch keys at `:677-679,:709-710` | yes |
| D0 lower bound | `family_barrier.py:80-84` ✔; the scorer skips days before D0 at `score_live_trials.py:724-725` | yes |
| Terminal upper bound | `family_barrier.py:85-91` ✔; skipped at `:726-730` | yes |
| Station census | `family_barrier.py:92-96` ✔; the tally invokes the barrier after the prefix filter at `family_tally_v2.py:818,838` | yes |
| Directory partition | the scorer writes `--derived-dir "$STORE_DIR/$FAMILY_ID"` (`score-live-trials-run.sh:314-328`); the tally reads the per-family dir (`family-tally-v2-run.sh:28-34,307-311` ✔); the deploy test pins it (`test_family_tally_v2_deploy.py:201-213`) | yes |
| Residual sidecar read | `family_tally_v2.py:849-850,1115-1158`; `residual_fills.py:234-246` ignores blank/non-residual `no_taken_latch` rows | yes |
| Admissible draws | `realized_draws.py:249-278` reads one family dir; `promotion_proposal.py:295-303` defaults to `root / champion.family_id` | yes |

## New paths merged 09-27, checked
- The EDGE-2 `fill_by_day/<day>` index is NOT family-keyed. It is only a boot spend-seed candidate index inside exec state (`client.py:427,2130-2166,4454-4472`). The scorer and tally read `fill/` records plus family latch prefixes, never `fill_by_day`, so it opens no cross-family path.
- The EDGE-3 per-family halt is family-keyed (`trial_day_latch.py:315-319`, wired from `manifest.family_id` at `app/trade.py:519-557`). It adds no tally or sidecar path.

## Residual caveat
`family_tally_v2.py --store-dir` accepts any directory. Isolation rests on the deployed wrappers passing the per-family dir, and a deploy test pins that. A hand-run with a wrong `--store-dir` is not guarded by the barrier's directory choice, but the four per-row barrier checks still refuse foreign rows.
