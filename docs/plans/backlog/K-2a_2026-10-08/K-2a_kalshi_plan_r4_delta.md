# docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r4_delta.md
Applies on top of K-2a_kalshi_plan_r2.md and K-2a_kalshi_plan_r3_delta.md; this delta wins.
Status: DRAFT; trading-bot-architect, prediction-market-reviewer and security-reviewer sign-off pending.

1. **Authority/ROI:** strike §10’s “live enablement operator-only,” r3’s matching restriction and WB-10’s operator handoff. Bot-owned Kalshi enablement uses AUTO-PROMOTE-RETIRE r3; the operator decides only the three spend caps ([r2:406](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md:406), [r3:13](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r3_delta.md:13)).
2. Account eligibility, funding and valid credentials remain external readiness requirements; they confer no trading authority and introduce no additional operator strategy decision.
3. Preserve GAP-6 GO as build authorization only. WB-7 produces the SEARCH comparator and power result; KC-n is the registered family that may arm ([r3 R3-6:22](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r3_delta.md:22), [R3-8:38](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r3_delta.md:38)).
4. REGISTERED permits KC-n registration only after the WB-4 both-ledger α test passes. Preserve shared totals, later PM.us allocation narrowing, measured Kalshi inputs and climate-day dependence; UNDERPOWERED_NOT_REGISTERED cannot arm ([r3:29](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r3_delta.md:29), [r2:482](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md:482)).
5. Freeze KC-n PREREG before any confirmatory-window read/run, naming sizing and ONE look; SEARCH∩confirmation remains empty. REGISTERED and SEARCH PASS alone never establish efficacy.
6. After registration, the bot applies AUTO-PROMOTE-RETIRE’s frozen efficacy + with-guards power PASS + three-cap decision, then its existing ACTIVATE/permit path. Adapter, venue-identity, reconciliation and safety acceptance must already be implemented and green.
7. KC-n consumes SIZE-UNDER-CAPS r2 `size()` directly. Shared daily/position/monthly authorization counts both venues, held/working exposure and reboot seeds; no separate venue cap, operator q or proposal-only mode.
8. Preserve WB-9a venue-bound permits and WB-9b’s one-node/shared-ledger architecture ([r2:356](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md:356), [r2:362](/home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md:362)).
9. The orders-off drop-in remains process-wide: KC-n ARM cannot clear a global disarm or re-enable retired PM.us. Within WB-9b, prove independent family permit withholding; otherwise fail closed and replan, never launch a second process.
10. Retirement uses AUTO-PROMOTE-RETIRE’s restrictive/cancel/registry path. Global DISARM uses the same orders-off actuator; family-local retirement must preserve the other venue’s lawful reconciliation and exits.
11. Every automated enable/disable leaves registry-linked durable receipts and an alert; boot/refusal/crash recovery uses the same mechanism, never a Kalshi-specific bypass. Security-reviewer signs off the shared actuation integration.
12. Preserve Nautilus immutability, `allow_short=False`, all settlement/safety/contract/pin tests, frozen PREREG/ONE look and NO-SEND execution firewall. Public schedule/credential readiness never licenses test execution egress.
13. **RED-first tests added:** GO/SEARCH/REGISTERED alone cannot arm; over-budget either ledger refuses; missing efficacy/power/monthly cap refuses; qualified KC-n reaches venue-bound permit through ACTIVATE; wrong-venue permit refuses; restart cannot double-spend; Kalshi arm cannot revive retired PM.us; receipt/alert recovery is idempotent.
14. **Pins moved:** KC-n PREREG/manifest/sizing hashes, Kalshi registry/live-gate composition authorization, venue-bound permit exact contracts, shared-node/supervisor/sandbox sets and affected closure hashes. Preserve the single production issuer and firewall predicates; widen only reviewed exact expectations.
15. Run focused cross-venue tests and import contracts, mutation-fails→restored-GREEN, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/kalshi-enable`; read EXIT.

Unverified / pending:
- Codegraph and Sequential Thinking MCP were unavailable; citations above were verified by direct file reads.
- Live fill count, registry contents, installed drop-in and cancellation/restart behavior were not independently checked; zero fills is the supplied ruling and recorded project state.
- “≈11-14” is approximate: the ruling specifies D0=10-25 and day 21; exact calendar convention needs reconciliation without changing the frozen rule.
- Monthly-cap delivery, accessor readiness, admission completion, power results and all proposed tests remain unverified; no tests ran and no files were edited, created or staged.

Codex session ID: 01a199a7-edf5-77f1-ab5f-08ba79eee2ae
Resume in Codex: codex resume 01a199a7-edf5-77f1-ab5f-08ba79eee2ae
