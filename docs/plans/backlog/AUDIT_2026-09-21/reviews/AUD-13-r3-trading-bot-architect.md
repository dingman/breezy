# AUD-13 review — round 3

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
sha256: 01e9c2290bf0c2f89923fe48f5b2ef405e97f0423afe34df6ea22540001371de
Round: 3
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-2 disposition audit

Round 2: this reviewer 97/100, silent-failure-hunter 98/100, both zero MATERIAL, one MINOR each
(both about the ~40 stale 09-12-plan citations not being a gated, checked step). Re-verified this
revision's response: §7 13b now carries **step 0**, a mandatory, gated citation-re-derivation
checklist an implementer may not proceed past, and §8 item 12 makes the resulting table an
acceptance artefact. **CONFIRMED closed** — this is exactly the required change both round-2
records asked for, not a narrower or reworded version of it.

## Claims re-verified this session, independent of the plan's own text

**The four-step detail-enum ladder and the "OrderEmulator RUNNING latch is the only
discriminator" claim — read from installed Nautilus source, per the brief's specific request:**

```
.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py
  987  def start(self) -> None:                      # SYNC variant -- no guards at all
  ...
  999      self._emulator.start()
 1000      self._initialize_portfolio()
 1001      self._trader.start()
 1003  async def start_async(self) -> None:           # the guarded variant
 1024      if not await self._await_engines_connected():
 1025          return
 1026      if self.exec_engine.reconciliation:
 1027          if not await self._await_execution_reconciliation():
 1029              return
 1033      self._emulator.start()
 1034      self._initialize_portfolio()
 1036      if not await self._await_portfolio_initialization():
 1037          return
 1039      self._trader.start()
```

This confirms the substance the plan relies on: a failed reconciliation returns at `:1029`,
**before** `_emulator.start()` (`:1033`) and `_initialize_portfolio()` (`:1034`) ever run — so in
that path `portfolio.initialized` stays `False` **and** the `OrderEmulator` never publishes
`RUNNING`. A portfolio-initialization failure (reconciliation already succeeded) reaches
`:1033-1034` first, so the emulator **does** start and publish `RUNNING` before the later
`:1036-1037` return. That is exactly the discriminator the plan's four-step ladder depends on,
and it holds.

**Two citation defects found, neither previously caught in two rounds of review:**

1. **MINOR — wrong method name.** The plan's §2 evidence table and §3 both attribute the guarded
   early-return logic to `NautilusKernel.start()`. The guards live in `start_async()`
   (`kernel.py:1003` onward), not in the sync `start()` (`kernel.py:987-1001`), which has **no**
   early returns at all and unconditionally runs `_emulator.start()` → `_initialize_portfolio()`
   → `_trader.start()`. Confirmed independently that Breezy only ever reaches this through
   `TradingNode.run()` (`live/node.py:283`), which internally awaits `self.kernel.start_async()`
   (`live/node.py:349`) — so the plan's *mechanism* is sound and reachable in production, but its
   citation names the wrong of the two methods. A reader who greps `def start(` in isolation
   would find the unguarded method and could wrongly conclude 13d's premise is false.
2. **MINOR — an acknowledged correction was only partially applied.** §2's evidence table states
   the `return` is "11 lines ABOVE `self._trader.start()` at `:1038`." §6 states, in the same
   document: "with `self._trader.start()` at `:1039` — the plan's earlier `:1038` was one line
   off and is corrected here." `self._trader.start()` is in fact at `:1039` (confirmed above) —
   so §6's correction is right, but §2's original `:1038` was never actually updated; the document
   now contains both the wrong number and a claim that it was fixed. This is the same class of
   defect flagged and fixed for AUD-15 in round 2 (a correction applied in one place, not
   throughout the document) — not fatal, but exactly the kind of thing this backlog's own history
   shows compounds across rounds if left unrecorded.

Neither defect changes the substance of any acceptance criterion or test in §7/§8 — the ladder,
the discriminator, and the test-with-real-engine design are all correct and independently
reproduce. Both are citation-accuracy defects in evidence the plan asks a reviewer/implementer to
trust verbatim, which is why they are recorded rather than waived.

**Required change:** in §2 and §3, replace "`NautilusKernel.start()`" with "`NautilusKernel.
start_async()`" everywhere the guarded logic is described, and fix the stray `:1038` in §2 to
`:1039` to match §6's already-stated correction.

## Other claims re-verified, no new defect

- `Trader(Component)` → `ComponentStateChanged` publication on `events.system.*`
  (`trading/trader.py`, `common/component.pyx:1941-1966,2211-2228`) — not re-derived from Cython
  source this session (round 2 already did this from source and it is unchanged); no reason to
  doubt it given the kernel-level ordering above is independently confirmed consistent with it.
- `position_check_interval_secs` exclusion, contract-pinned — unchanged, not re-litigated.
- R-1/R-2 blockers — correctly still named as blockers, not decided by this plan, consistent with
  the brief's instruction that operator/strategy-lead judgment calls must be surfaced, not made.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 19/20 — unchanged from round 2's reasoning; G-10
  fully covered, boot-halt path added and independently reproducible.
- Technical correctness and evidence grounding: 18/20 — the load-bearing mechanism (the ladder,
  the discriminator, the reachability via `start_async()`) is independently confirmed correct.
  Deducted 2 (not the 1 carried from round 2's ~40-citation residual, now closed by step 0): for
  the two citation defects above — a wrong method name in a load-bearing evidence table, and a
  correction claimed in §6 but not applied to the duplicate figure in §2, found on direct source
  read rather than by trusting the plan's own quotations.
- Implementation specificity and feasibility: 14/15 — unchanged from round 2; the detail ladder is
  literal, step 0 is a completable gated checklist. The real-kernel timeout fixtures for 3b remain
  the implementer's hardest unscoped mechanics, as round 2 already noted.
- Acceptance criteria and validation quality: 20/20 — twelve items including the six-symbol-diff
  equivalent negative check via the boot-halt/self_check separation, the cross-assertion in 13d
  step 3b, and the incident replay. Unaffected by the citation defects.
- Autonomous operation, failure handling, recovery: 15/15 — F1-F6 fall closed with latched reasons
  and alerts; F5 is a delivered CRITICAL with a real-engine test; no unwarranted self-healing.
- Portfolio objective alignment, scope, dependencies: 9/10 — unchanged, carried per round-2
  disposition 5 (the P2 rationale is an argued priority call, not derived from a measured cost;
  there is no measured cost to derive it from, and inventing one would be worse).

**Total: 95/100**

## Required changes for full marks

- Fix the two citation defects: rename `NautilusKernel.start()` → `start_async()` everywhere the
  guarded early-return logic is described in §2/§3, and correct the stray `:1038` in §2's
  evidence table to `:1039` so it matches §6's own stated correction.

## Blockers

- R-1 (fee unit on a reconciled `FillReport`) and R-2 (may a reconciled `OrderFilled` reach
  `on_order_filled`) remain correctly named, undecided strategy-lead rulings blocking 13b/13c
  only. Not waivable by this review. 13d has no blocker and is independently actionable.
