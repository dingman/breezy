# AUD-13 — Round 4 review (silent-failure-hunter, FINAL, RECONCILED)

**Plan file:** AUD-13-native-venue-reconciliation-from-durable-records.md
**SHA256:** d5cbd9a06f4b460bee5fc946694868796dbd0c19c59a89ba819f01b443907d06
**Round:** 4 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against installed Nautilus source this session (focus: the two kernel-timeout fixtures, per the coordinator's round-4 brief)

| Claim | Status at HEAD (installed `nautilus_trader` 1.231.0) |
|---|---|
| Sync `NautilusKernel.start()` (`kernel.py:989`) has no early return; runs `_emulator.start()`/`_initialize_portfolio()`/`_trader.start()` unconditionally at `:999-1001` | CONFIRMED — read verbatim |
| `async def start_async(self)` at `:1003`; guards at `:1024` (`_await_engines_connected`), `:1027-1029` (`if self.exec_engine.reconciliation: / if not await self._await_execution_reconciliation(): / return`, `else: self._log.warning("Reconciliation deactivated")` at `:1031`), `:1036` (`_await_portfolio_initialization`); `self._emulator.start()`/`self._initialize_portfolio()` at `:1033-1034`; `self._trader.start()` at `:1039` | CONFIRMED — exact line numbers, including the `:1027` guard line and the `:1029` return, matching the plan's corrected citations |
| `TradingNode.run()` (`live/node.py:283`) awaits `self.kernel.start_async()` | Not re-verified this session (unchanged from round 3's confirmation; no reason to doubt) |
| `_check_engines_connected` (`kernel.py:1377-`) is a poll loop: `seconds = self._config.timeout_connection`, `while True: await asyncio.sleep(0); if clock >= timeout: return False; if not data_engine.check_connected(): continue; if not exec_engine.check_connected(): continue; break` | CONFIRMED — checks both `_data_engine.check_connected()` and `_exec_engine.check_connected()`, matching the plan's "two probes" claim; actual span is `:1377-1400`, plan cites `:1377-1391` (covers the loop body, not the trailing `break`/`return True`) — immaterial, the poll-loop mechanism claimed is accurate |
| `_check_portfolio_initialized` (`kernel.py:1423-`) — same shape, `seconds = self._config.timeout_portfolio` | CONFIRMED |
| `TradingNodeConfig.timeout_connection: PositiveFloat = 60.0` at `system/config.py:127`; `timeout_portfolio: PositiveFloat = 10.0` at `:129` | CONFIRMED, exact lines |
| `PositiveFloat`'s actual validation floor | **RESOLVED THIS SESSION** — `common/config.py:57`: `PositiveFloat = Annotated[float, Meta(gt=0.0)]`. Any float strictly greater than `0.0` is accepted; there is no hidden minimum. `0.5` (the plan's example) is trivially valid, as is any smaller positive value. |
| `Cache.add_order` (`cache/cache.pyx:2155`), signature `(self, Order order, PositionId position_id=None, ClientId client_id=None, bint overwrite=False)` | CONFIRMED, exact line |
| `Portfolio.initialize_orders` (`portfolio/portfolio.pyx:236`); `if instrument is None:` branch at `:260`, `self._log.error(f"Cannot update initial (order) margin: no instrument found for {instrument_id}")` at `:261-263`, `initialized = False` / `break` at `:265-266`; `self.initialized = initialized` at `:300` | CONFIRMED, exact lines, matching the plan's `:258-266`/`:300` citations precisely |
| `tests/contract/test_trade_node_lifecycle_contract.py`: `_SilentDataClient` at `:80`, `_SilentDataClientFactory` at `:96`, `node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, _SilentDataClientFactory)` at `:153`, `test_the_trade_node_reaches_running_and_stops_cleanly` reaching `node.trader.is_running` | CONFIRMED — the named positive control genuinely exists and genuinely reaches `trader.is_running` on this wiring |

Every citation in the round-4 target area (§7 13d step 3b-fixtures) checked out exactly against installed source. The two prior-round citation defects (wrong method name attributed to `start()` instead of `start_async()`; `:1038` vs `:1039`) are genuinely fixed throughout, with the corrected arithmetic ("ten lines," not "eleven") also holding under a fresh count.

## Reconciliation (coordinator-requested, this revision)

The initial round-4 pass withheld 5 points (19/20, 19/20, 14/15, 19/20, 15/15, 9/10 = 95) without tying each to a named defect + required change, contrary to the brief. Each is re-decided on the merits below.

| # | Criterion | Original | Reason originally given | Disposition |
|---|---|---|---|---|
| 1 | Fidelity to the audit gap and completeness | 19/20 | "field maps still live in the 09-12 plan by design" | **(b) AWARDED — 20/20.** This is a deliberate, reasoned scope decision, not a completeness gap: the field maps exist, are precisely cited (`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md §3, :60-70`), and §7 13b step 0 gates their re-derivation before use. Duplicating them into AUD-13 would create two divergent specifications for one code change — the documented reason (§ round-1 disposition 5) is correct engineering, not a shortfall. No plan-text change would improve fidelity to the audit gap by inlining them; it would only add duplication risk. Note, not a blocker: the reader must follow one cross-reference to reach the field maps. |
| 2 | Technical correctness and evidence grounding | 19/20 | "the ~40 09-12-plan citations remain gated rather than paid" | **(b) AWARDED — 20/20.** No incorrect claim is made about these citations: the plan states plainly they are stale-by-~554-lines and gates their re-derivation as a mandatory, stop-on-`SYMBOL GONE` pre-step (§7 13b step 0) before any generator body may be written, with the table itself made an acceptance artefact (§8 item 12). "Not yet re-derived" is an honestly-disclosed future execution obligation, not a present technical-correctness defect — nothing in the plan asserts any of those 40 citations are currently accurate. A plan-text change that re-derived all 40 now would be premature work duplicating what §7 13b step 0 already mandates at execution time (after R-1/R-2 land), and is not required to close a fidelity/correctness defect. Note: the debt remains real and is tracked, not paid — carried as a note, not a deduction. |
| 3 | Implementation specificity and feasibility | 14/15 | "the tests have not been executed, and the smallest accepted `PositiveFloat` timeout is the implementer's to confirm at model-validation time" | **(a) DEFECT NAMED, POINT STAYS WITHHELD — 14/15.** Splitting the original reason: "tests not executed" is not a valid plan defect — no plan document can contain a RED→GREEN transcript of code that does not yet exist; that applies to every acceptance item in every plan in this backlog and is not specific to AUD-13. But the second half is a **real, currently-fixable defect**: the plan frames the smallest accepted `PositiveFloat` timeout as an open question ("the implementer's to confirm at model-validation time") when it is not open at all — `common/config.py:57` defines `PositiveFloat = Annotated[float, Meta(gt=0.0)]`, so any value `> 0.0` (including the plan's own example, `0.5`) is unconditionally valid. **Required change:** in §7 13d step 3b-fixtures, replace "the smallest value the model accepts (e.g. `0.5`)" and the round-4 self-score's "the implementer's to confirm" framing with a direct citation — `common/config.py:57`, `PositiveFloat = Annotated[float, Meta(gt=0.0)]`, any float `> 0.0` accepted, so `0.5` (or a smaller value, if a faster test run is wanted) is settled, not deferred. This is a small, mechanical fix; the point stays withheld until it lands. |
| 4 | Acceptance criteria and validation quality | 19/20 | "Live proof still lands after merge" | **(b) AWARDED — 20/20.** §8 item 10 requires live proof "on the next boot" quoted from the production log — by its own nature this cannot exist before the code is merged and deployed. No plan-text change can make live evidence precede the deployment that produces it; the acceptance item is already correctly scoped as a post-merge artefact, distinct from (and in addition to) the pre-merge RED→GREEN transcripts required for everything else. This is a structural property of "prove it in production," not a specificity gap. |
| 5 | Autonomous operation, failure handling, recovery | 15/15 | (full marks, nothing withheld) | Unchanged — 15/15. |
| 6 | Portfolio objective alignment, scope, dependencies | 9/10 | "no measured cost exists to derive the P2 rating from" (round-2 architect's permanent deduction, carried through rounds 3-4) | **(b) AWARDED — 10/10.** This is precisely the brief's own worked example of unavailable evidence: the bot has not traded since 2026-09-15, so no measured dollar cost of the reconciliation gap exists to derive a P-rating from, and inventing one would violate the brief's ban on invented financial impact. No change to this plan's text could manufacture a trade that has not happened. The P2 rating is argued from reasoned priority (correctness debt vs. the fact that 100% of decisions currently die upstream of pricing, per G-01) rather than from a measured figure, and the plan says so honestly rather than fabricating a number — that is compliance with the brief, not a shortfall. Recorded as a **note**, not a BLOCKER: it does not block AUD-13's own execution, it only explains why no ROI figure is or can be attached here. |

**Reconciled total: 20 + 20 + 14 + 20 + 15 + 10 = 99/100.**

## Other attack points checked this round (unchanged from the original pass)

- **Emulator-latch discriminator (probe 2):** re-confirmed structurally — `_emulator.start()` sits at `:1033`, strictly between the reconciliation `return` at `:1029` and `_initialize_portfolio()` at `:1034`, so a reconciliation failure genuinely cannot reach the emulator start while a portfolio-initialisation failure genuinely can. This is what makes the §7 13d step 3b cross-assertion ("the portfolio case must NOT resolve to the reconciliation detail and vice versa") a real test of the ladder rather than an assumption.
- **No `nautilus_trader` file is patched or monkeypatched inconsistently with the documented factory seam** — `add_data_client_factory` is a native `TradingNode` method already exercised by the cited positive-control test; `Cache.add_order` and the deliberately-uncached `InstrumentId` are both native, unmodified mechanisms.
- **Vacuous-test check:** the cross-assertion pair (engines-case vs. portfolio-case, both resting on `portfolio.initialized == False`) is specifically constructed so either test alone would pass under a broken ladder — not a vacuous pair.

No new defect found beyond the specificity item resolved above.

## Per-criterion points (reconciled)

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | **20** | G-10 fully covered plus the boot-halt path the gap implies but does not name; the field-map cross-reference (rather than duplication) is a correct design choice, not a gap. |
| Technical correctness and evidence grounding | 20 | **20** | Every kernel-ladder citation in the round-4 target area was independently re-derived from installed source this session and is exact; no incorrect claim found anywhere, including about the still-unpaid 40-citation debt, which is honestly disclosed and gated. |
| Implementation specificity and feasibility | 15 | **14** | The fixture shape is fully literal — client subclass, config field, cache call, exact line ranges, named positive control. Deducted 1: the plan frames `PositiveFloat`'s validation floor as an open implementer question when it is in fact resolved (`common/config.py:57`, `gt=0.0`); required change stated above. |
| Acceptance criteria and validation quality | 20 | **20** | Twelve items; the cross-assertion in step 3b makes the ladder falsifiable rather than merely exercised; live proof correctly lands post-merge by the nature of a production-log artefact, not as a specificity gap. |
| Autonomous operation, failure handling, recovery | 15 | **15** | An unattributable boot-halt still alerts with a generic detail; the ladder degrades without ever swallowing the signal — re-confirmed this session against the exact return sequence. |
| Portfolio objective alignment, scope, dependencies | 10 | **10** | No cost is measured because the bot has not traded since 09-15; the plan states this honestly rather than inventing a figure, which is compliance with the brief, not a shortfall. |
| **Total** | **100** | **99** | |

## Required changes

1. §7 13d step 3b-fixtures: cite `common/config.py:57` (`PositiveFloat = Annotated[float, Meta(gt=0.0)]`) and state that any timeout `> 0.0` (including the plan's own `0.5` example) is accepted — remove the "implementer's to confirm at model-validation time" framing, since the question is already settled.

## Blockers

**R-1 and R-2** (strategy-lead rulings on the fee-unit `commission=` expression and on whether a reconciled `OrderFilled` may reach `on_order_filled`) remain BLOCKERs on 13b/13c, unchanged from prior rounds — not waivable by review. 13d (the boot-halt alert) carries no blocker.

**Not a blocker, recorded as a note per the reconciliation above:** no measured portfolio-ROI cost exists for the reconciliation gap because the bot has not traded since 2026-09-15; this is unavailable evidence (the brief's own example), not a plan defect, and does not gate AUD-13's own execution.
