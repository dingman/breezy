# AMBIG-LATCH-RESUME r5: merged blind review (2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| trading-bot-architect | 92 | 0 |
| security-reviewer | 91 | 0 |

## Verified

- **DH1 two-phase.** A deadlock is impossible. The node-side marker gate fails closed, and the pid and start-ticks check rejects stale and reused pids.
- **DM3 ties.** Safe under the "non-increasing" rule.
- **DM1 window.** Adequate.
- **DM2 scan coverage.** Sound.
- **CRITICAL for no-id launch-to-resolve.** Accepted.
- **DM4 is operator-free and safe.**

## Owed in r6

1. **[MED, both] The DM4(b) bound is misstated.** Same-day membership comes from `_instrument_provider.list_all()` (`client.py:2923-2936`). A take before 16:40Z on day D is relaunched at 16:50Z on D, with the market still loaded, so the real exit can be 16:50Z on D+1.

   **Coordinator ruling.** Do both of the following:
   - **(a) Add route (d).** In the same eof-complete activities scan, reconcile the foreign-holding delta against the in-window MANUAL aggressor legs, which are already parsed `manual=True`. If the delta equals the signed sum of those legs, treat the holding as consistent. This clears the typical manual-trade trigger within the 60 s re-check. Anything else stays AMBIGUOUS.
   - **(b) Restate the residual bound.** It is at most two daily cycles from the take. Test the first-relaunch case.
2. **[MED, security] Mixed-type ordering can starve liveness.** `_activity_create_ts_ns` (`account_activity.py:569`) uses a different timestamp field for each row type. Check ordering on TRADE rows only, or prove the venue sorts all types by one key using a capture that contains positionResolution and balance rows. Pick one and state why.
3. **[LOW] Phase-A ancestry check.** Rely on `git merge-base --is-ancestor` alone, not on the committer `%ct` time, which survives a rebase.
4. **[LOW] DM1 forward skew.** State that the 55 s forward skew is symmetric by choice and not derived, or tighten it with evidence.
5. **[LOW] T48 scope.** Note that T48 checks only the module's own imports. `account_activity` is pure today; pin that too, or state it.
