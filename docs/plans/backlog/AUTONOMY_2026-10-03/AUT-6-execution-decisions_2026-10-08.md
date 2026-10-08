# AUT-6 execution decisions (2026-10-08, coordinator)

Binding inputs:
- `AUT-6-drift-health_plan_r15.md`;
- `reviews/AUT-6-r15-final.md`, which binds `AUT-6-r13-final.md`;
- `reviews/ARCH-ERRATA-rev9_2.md`.

The WP decomposition was done by the planner, read-only, on 2026-10-08. Only WP1 can be built end to end today.

## Decisions (planner defaults, adopted)

| # | Decision | Ruling |
|---|---|---|
| X-1 | Rows 6 and 7 deadlock: row 7 needs 6, and AUT-6 WP1b/5b/6/8 need row 7 | Split row 6. **6a** = WP1, WP2, WP3, WP3b, WP5 and WP9 (code). **6b** = WP1b activation, WP4, WP5b, WP6, WP7 and WP8, gated on rows 5 and 7 as listed. When 6a is DONE, 7a can start. |
| X-2 | The plan's writer id `legacy-<component>` (l.864) never matches AUT-1's reader regex `[a-z0-9_]{1,64}` (`capture_aut6_contract.py:48`) | Use `legacy_<component>`. |
| X-3 | The redeliver unit's `OnFailure=breezy-autonomy-failed@%n.service` target does not exist until WP4/WP7 | Ship the line and enable the timer now. Record the gap. Until then, check-alerts and AUT-1's delivery-record reader cover it. |
| X-4 | AUT-1 rows with `network="none"` cannot deliver | Give them a write-only `enqueue` API. Redeliver drains those entries, with no `f` record per entry. |
| X-5 | WP4's storm constant exists only in adapters (`recorder_watchdog.py:81`), and AUT-6 may not import adapters | Move it to `domain/` with an adapter alias, and have AUT-6 read it from `domain/`. This happens in WP4. |
| X-6 | `node_liveness`/`permit_lapsed` with FQ v1 orders off and permit capability absent | Before WP6, check the live permit state. If no permit is minted, add a case for orders off or halted, or the detectors page falsely. |
| X-7 | Score 3 (live proof) is unreachable under RULING_FQ-v2-NO-TRADE_2026-10-08 | Build WP9, and score it "machinery proven". The live-proof window opens only when a family sends again. |

## Stale plan anchors (fix them when you implement; do not edit the plan)

- l.1124/1129: ARCH-0 now owns the wrapper and table (`runtime/autonomy_sandbox/table.py:324`). The wait is already met.
- l.894: there are now five node sites: `trade.py:474,533,782,1201` and `node_config.py:521`.
- l.1142: `tests/unit/test_systemd_unit_contracts.py` does not exist. Use `tests/contract/test_autonomy_units*.py`.
- §3.8: the list of failing units dates from 10-02. Re-check it before WP3.
