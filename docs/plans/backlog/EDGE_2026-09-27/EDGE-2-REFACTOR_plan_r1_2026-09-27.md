# EDGE-2-REFACTOR plan: decompose `_resolve_ambiguous_intents`

**Recommendation: defer the refactor (about 75% confidence). Do the characterization tests now; they change no source.** The main reason is that each extracted helper has to be added to the NOSEND firewall allowlists. That is an edit to a safety test, and the code's own comments say the inlining was chosen to avoid exactly that.

The function runs from `src/breezy/adapters/polymarket_us/exec/client.py:2326` to `:2855` (about 530 lines). All `client.py` line numbers below are from that file. Nothing was edited or run.

## 1. Seams (the phases of one pass)
| # | Phase | Lines | Kind | Early exits |
|---|---|---|---|---|
| S0 | Loop, one-shot return, backoff sleep | 2386-2415 | sync calc + sleep | return at 2394 |
| S1 | Latch guard | 2416-2418 | sync | continue |
| S2 | Startup-evidence refresh (never counts as a failure) | 2434-2461 | async | none |
| S3 | Load and validate intent and context | 2462-2505 | sync | 5 continues |
| S4 | Stale-intent alert | 2513-2536 | sync | none |
| S5 | Find or load the instrument, plus backoff | 2537-2602 | async | continue |
| S6 | Order GET, unwrap body, parse, reset backoff | 2603-2660 | async | 3 continues |
| S7 | Classify status (partial / terminal-zero / fill) | 2662-2693 | pure | 2 continues |
| S8 | Positions read, leg, slug, `long_state` | 2695-2724 | async | 3 continues |
| S9 | Stamp the H2 marker, then the trade-activity join | 2726-2750 | async | none |
| S10 | Terminal-zero decision | 2752-2838 | sync | 6 continues |
| S11 | Fill decision | 2839-2855 | sync | 1 continue |

- The only inner loop (2805-2808) uses `break`, never `continue`. So every `continue` in the body can become `return` when the body moves into its own method.

## 2. Constraints that make this expensive
- **Firewall guard.** `find_exec_resolver_violations` (`tests/unit/test_execution_egress_firewall_guard.py:2409-2470`) scans functions by name and flags any callee not on the allowlist.
  - Each extracted method needs a new row in `EXEC_RESOLVER_COROUTINES` (`:2082`) and `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2101`).
  - An async helper also needs a row in `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) and in the cage pin (`tests/unit/test_cage_rule_constants_are_pinned.py:331-347`), whose count goes up by one.
  - The code comments say the inlining was deliberate, to avoid new callees: `client.py:2396-2402`, `:2411`, `:2521`, `:2550-2556`.
- **Source-text tests will fail when code moves.** These must be pointed at the new method, with the same strength, and never weakened:
  - `tests/unit/test_current_rung_hold_ambiguous_resolver.py:940-946`
  - the same file, `:2598-2600`
- **Log lines cannot be observed in tests.** The Nautilus logger is read-only and caplog cannot see it (test file `:2541-2552`). Characterization tests must assert on state: counters, latch state, alert dictionaries, and `_private_read` call logs.

## 3. Characterization gaps
Each row below had no test in `test_current_rung_hold_ambiguous_resolver.py` by grep. Per L-33, each needs mutation RED evidence.

| Gap | Branch | What to pin |
|---|---|---|
| G1 | 2413 backoff cap | Sleep stays at the cap after 7+ failures. The existing test `:569-603` stops at 80 s. |
| G2 | 2416 latch is None | No GET is made; the pass survives. |
| G3 | 2446-2447 open-orders refresh fails while positions succeed | Error is recorded; the evidence record is still written. |
| G4 | 2485 intent is OPEN but has no context | No GET; the intent stays OPEN. |
| G5 | 2494 malformed context bytes | Stays AMBIGUOUS; failure counter unchanged. |
| G6 | 2500 context carries a foreign `intent_id` | Refuses to act; no GET. |
| G7 | 2524 stale alert when a failure kind exists | The alert's `last_failure_kind` is that kind, not "none". The test at `:608` never asserts this field. |
| G8 | 2621 flat (un-nested) GET body | Resolves the same as a nested body. Every fixture nests (test file `:201-203`). |
| G9 | 2623 GET body that is not a mapping | Failure counter neither increments nor resets. This differs from 2608/2647 and must be pinned. |
| G10 | 2698 positions read fails after a terminal GET | Counter already reset at 2660 and stays 0; `_resolved_by_get_ts_ns` is not stamped. |
| G11 | 2719 `long_state` is None, end to end | The helper alone is tested (`:3856`); the resolver branch is not. |
| G12 | 2746 join is skipped when `long_state` is True | No activities GET is made. |
| G13 | 2846 `_resolve_accept_fill` raises | Error counter increments; the intent stays OPEN. The test at `:1983` covers only the terminal-zero wrapper. |
| G14 | 2538 instrument missing and no loader wired | Needs checking against the test at `:886`. |

Branches already covered, at test-file lines:
- One-shot pass: `:2165`, `:2251`
- Refresh: `:2385`, `:2428`, `:2491`, `:2530`
- Corrupt latch: `:1709`
- Instrument loader: `:810-1058`
- GET exception: `:569`
- Mapping error: `:2741`
- Partially filled: `:1888`
- Non-terminal status: `:668`
- Slug derivation: `:3866`
- Contradiction: `:4170`, `:4225`
- Incomplete join: `:4062`, `:4095`, `:4369`
- Minimum age: `:3976`
- Same-day leg: `:4447-4572`
- Terminal-zero raise: `:1983`
- Fill not confirmed: `:1578`
- Fill confirmed by join: `:4623`

## 4. Extraction sequence (if the refactor goes ahead)
Each step is one commit. After each, `scripts/ci/run_tests_no_egress.sh`, `lint-imports` and ruff must be green.
0. Land G1-G14 as a characterization change with no source delta.
1. Move the loop body (2416-2855) into `async _resolver_pass()`, turning `continue` into `return`. The loop keeps S0 only. This adds guard rows in 4 sets and retargets the source tests at `:940` and `:2598`. It is the largest single step and captures most of the value.
2. Extract S7 as a pure module-level function returning a small frozen dataclass. One allowlist row.
3. Extract S10 and S11 as one sync method (`current.intent_id` equals `context.intent_id` because of the check at 2500). This is the multipage touchpoint.
4. Extract S3 (sync, returns `(current, context) | None`).
5. Extract S2 (async).
6. Extract S5 (async; mutates the backoff counter).
7. Extract S6 (async; mutates and resets the backoff counter).
8. Extract S8 (async).

Ordering invariants:
- The H2 stamp at 2730 stays after S8 and before the join.
- The backoff reset at 2660 stays before S7.

## 5. EDGE-2-MULTIPAGE interaction
- Multipage changes completeness inside `_order_trade_activity` (`client.py:3167-3237`). `created_ns` is already passed in for that purpose (`:3180-3182`), and `TradeJoin.complete` is documented as EOF-only (`:1517-1530`).
- The resolver only reads `join.complete` and `join.trade_count` (2747, 2779, 2841).
- So multipage needs no edit to the resolver body. If it ever did, only S9-S11 would matter, which is step 3.

## 6. Risk register
- **HIGH: firewall allowlists grow by about 10-15 rows in a NOSEND safety test.** Mitigation: L-12 style widening only, one commented row each, a security review, and never a relaxed comparison.
- **HIGH: the resolver runs in the live node.** A merged change only takes effect after a respawn (restart window 01:00-16:40Z). A regression would bring back L-48 (a latch nothing can clear).
- **MEDIUM: backoff counter ordering across S5, S6 and S7** (2582, 2608, 2647, 2660). Covered by G9, G10 and the existing test at `:569`.
- **MEDIUM: `client.py` is a hot file** (EDGE-2, 2C, FU-8 recently). Expect conflicts; take the full gate after every merge (L-43).
- **LOW: turning `continue` into `return` inside try/else** at 2436-2461. The refresh branch has no `continue`, so this is mechanical.

## 7. Why defer
- **YAGNI.** The refactor changes no behaviour, multipage does not need it (section 5), and the resolver has had many recent fixes that each landed as small inline edits.
- **It weakens more than it strengthens.** It mostly adds audited callee surface to the firewall, which the inline comments explicitly chose to avoid.
- **It does not meet the file standard either.** `client.py` is 5,710 lines against an 800-line limit, and extracting methods adds lines. Fixing that needs a module split, which is a separate item.
- **Most comment-heavy phases would still be over 50 lines.** S5 (65 lines) and S10 (86 lines) need a second split, so the effort doubles.

Action: do step 0 now. Park steps 1-8, and do step 1 only when a real behaviour change next has to touch the resolver body.
## Coordinator disposition (2026-09-27)
ACCEPTED: DEFER steps 1-8. Evidence: every extracted helper widens the NO-SEND firewall allowlists, which is exactly what the inline comments chose to avoid; multipage needs no change to the resolver body (section 5); client.py (5,710 lines) needs a module split in any case. Step 0, the characterization tests G1-G14, is scheduled AFTER EDGE-2-MULTIPAGE merges, because both edit tests/unit/test_current_rung_hold_ambiguous_resolver.py. Re-open step 1 only when a real behaviour change next has to touch the resolver body.
