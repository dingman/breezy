# AUT-4 r5: merged (coordinator). prediction-market-reviewer 95 (READY), mle-reviewer 93. Final 93; zero CRITICAL or HIGH. Patch to r6.
- **L1 [pm 1, mle 1]**: Fix the K8 off-by-one. Request `TimeoutStartSec` ≤ 4139 s for the 09:35Z start, or ≤ 4799 s from 09:24Z, so that `start + 1 s + TimeoutStartSec + TimeoutStopSec ≤ 10:45:00`. Make the §5/§6.4 row 9 requests match.
- **L2 [pm 2]**: Use 09:35Z consistently for the AUT-3 rerun.
- **L3 [mle 2]**: State that the K9 look-time counts are functions of champion data only. Add a test that the look time is independent of the nominee's outcomes.
- **L4 [mle 3]**: Re-score.
