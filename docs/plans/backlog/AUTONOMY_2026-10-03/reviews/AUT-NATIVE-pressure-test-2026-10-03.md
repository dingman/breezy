# AUT-NATIVE: Nautilus/systemd/existing-code pressure test of AUT-2..AUT-7 (2026-10-03)

Each plan got one blind read-only tester. Null hypothesis: Nautilus 1.231.0 or existing Breezy code already provides each capability. Every tester was sent back until the whole plan was covered.

| Plan | Tester | Verdict | Disposition |
|---|---|---|---|
| AUT-2 r7 | trading-bot-architect | PASS | Binding build items (below). |
| AUT-3 r6 | mle-reviewer | PASS | Binding build items (below). |
| AUT-4 r6 | prediction-market-reviewer | PASS with reuse conditions | **r7 revision owed.** It duplicates existing Breezy code: `hypothesis_ledger.recompute_mde`/`alpha_remaining` (:861, :825) and the existing Wilson helpers. |
| AUT-5 r7 | architect | PASS | Binding build items (below): two §2 rejection rows. No design change. |
| AUT-6 r13 | silent-failure-hunter | **FAIL** | Native-first r14 owed: systemd `WatchdogSec`/`Restart=on-watchdog` replaces SELF_HEAL and the drill probe (`AUT-6-native-pressure-test.md`). |
| AUT-7 r5 | security-reviewer | PASS | Optional trims become build items. |

## Binding build items
**AUT-2**
- Test the native `Position.apply` oracle against `net_position.py` on single-leg q=1 cases. The runtime replacement is rejected for three reasons: float arithmetic, the commission-only realized PnL, and fills that are cumulative per order.
- Reconcile the `critical_dedup` semantics with the AUT-6 outbox dedupe in §3.7.3.
- State in §2 that `ResidualSettlement` is reused for exit-proceeds records.

**AUT-3**
- `AR/run_record.py` and the snapshot writers use one shared write-once helper built on the existing atomic writers (`nbp_derived_store.py:353`). Do not add a fourth copy.
- `c3_writer` imports `_resolve_candidate_root` (`nbp_learning_nightly.py:708`).
- `AR/locks.py` shares the existing `breezy-studies.lock` convention. WP6 documents why it waits rather than skipping.

**AUT-7**
- Optionally drop the `champion_history_*.json` render and its test, which duplicate the chain export.
- `post_verify` classifies only AUT-5a signals and never re-derives resolver state.

**AUT-5**
- Add §2 row: Nautilus `MaxDrawdown` and the tearsheet drawdown (`analysis/tearsheet.py:140-170`) are rejected. The plan's statistic is labelled settlement P&L divided by cumulative cost, so the native one is a different unit (L-44).
- Add §2 row: entry-only demotion is not served natively.
  - `TradingState.REDUCING` lets a flat-rung BUY through (`risk/engine.pyx:1150-1165`).
  - `HALTED` blocks exits and applies node-wide.
  - `Controller.stop_strategy` kills exits.
