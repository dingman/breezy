# AUT-4 r2: merged review (coordinator). prediction-market-reviewer 78, mle-reviewer 83. Final 78, NOT READY.

## Coordinator decision (binding)
`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ALPHA-decision.md` settles the α conflict:
- k_life is a lifetime index that never resets.
- K_max is a separate per-window mint limit.
- `K_LIFETIME_EFFECTIVE` (nominal beyond it) applies, with B capped and an exact or analytic tail.
- A window cap below n_min gives `INCONCLUSIVE(window_cap_below_n_min)` by construction, and a promotable path is not claimed.

ARCH Rev 7 will adopt this together with your P4-7 to P4-12. Write r3 against Rev 5 plus this decision, and list each ARCH dependency as a hard prerequisite.

## HIGH
- **F1 [pm1, mle N1, pm2, pm3]: adopt the ALPHA decision.**
  - Add `n_min_eff ≤ n_cap` to the feasibility record and to R-F.
  - State honestly that every FORWARD_SHADOW (a) is INCONCLUSIVE by construction under today's σ and X.
  - Cap B and set an effective horizon.
  - Correct the W1 arithmetic to Rev 5 (L_max 60 min + 150 s, margin ≥ 0.5 h).
- **F2 [mle N2]**: k is assigned at stage-1 nomination and stored in stage-1 metrics. Add `test_two_pending_nominees_get_distinct_k`.
- **F3 [mle N3]**: P4-10 (two ruling-sha fields) and P4-11 (`verdict_id` without the timestamp) are hard prerequisites in §6.4. Add a fallback acceptance test under the Rev 5 rule, so a FAIL can still DEMOTE.

## MEDIUM
- **F4 [pm4, mle N4]: the (b) joint bound.**
  - Split α_k/3 across the three bounds, or bootstrap `ev_eff` jointly.
  - Add `N_IOC_MIN` for `p_fill`.
  - Fix the survivorship direction: if misses are the favourable decisions, the bias is conservative.
  - Add a test.
- **F5 [pm5]: R-C.** Use a one-sided paired test with a margin, and fail closed when fewer than N buckets qualify. Include the conjunct's power in n_min.
- **F6 [pm6]: R-B pre-commitment.**
  - Derive n_max and the loss stop from the power arithmetic, and put the derivation in the design JSON.
  - Add a git-timestamp check that no FQ PnL artefact was read before the commit.
- **F7 [pm7]: live-proof coverage.**
  - The fixture or drill candidate path may satisfy the candidate-coverage rule.
  - State the score if AUT-3 nominates no real candidate. The target is still 3 by the fixture path, with the machinery-proven class stated.
- **F8 [mle N5]**: Offline expiry gap. Set `RuntimeMaxSec` so W + RuntimeMaxSec ≤ 7200 s − 15 min, or give the offline kind its own deadline and exempt it from the expiry clause. Note that `RuntimeMaxSec` does nothing on oneshot units; use `TimeoutStartSec`.
- **F9 [mle N6]**: Require one closure sha across the cited `fs_replay` outputs; otherwise `INCONCLUSIVE(mixed_closure)`.
- **F10 [mle N7]**: LIVE `n_min` is the first-look n. Restate checklist (c).
- **F11 [mle N8]**: Name the store for wall time and RSS. An ERROR verdict is not fresh.
- **F12 [mle N9]**: Define a per-run replay budget with a partial-commit rule for backlog days.
- **F13 [mle N10]**: Name the 360 s constant, and register `fs_replay` as a producer id in pins.

## LOW
- **F14 [pm8]**: Report the MDE-based power at n = 160 next to the table of probabilities of reaching n_max.
