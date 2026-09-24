# AUD-17 review — round 3

Plan: AUD-17-operator-caps-proven-through-the-v4-live-composition.md
sha256: 5e5877c745c2a299acf639e5c04436aae6118791670476caae8924e6fc7f8f87
Round: 3
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-2 disposition audit

Round 2: this reviewer gave 100/100; silent-failure-hunter gave 95/100 with 1 MINOR — the §7 17a
step 2 fallback hedges the reason-equality sub-assertion but did not originally state the
consequence for the test's own pass/fail shape. Re-verified this revision's text: §7 17a step 2
now states plainly that on fallback the per-position denial test **still PASSES** on exact-type
discrimination plus the differential alone, is not skipped or xfailed, and that (a) the fallback
and the scan output that forced it must be recorded in the transcript, (b) dropping assertion 2 is
the only permitted response (never touching the assignment scan). **CONFIRMED closed** — this is
exactly the required change, stated in both §7 and reinforced in §9's "costs nothing" argument.

## The specific mechanism this brief asked to be re-verified — fresh from source this session

**`operator_controls.py`, read directly, not from any prior round's quotation:**

```
:384-387  position_cap = operator_max_position_cost_usd()
          if cost > position_cap:
              raise LiveTradingPermissionError(...)      # plain, no subclass
:126      class DailyBudgetExhausted(LiveTradingPermissionError):   # distinct subclass
:120      "Operator ruling 2026-09-14: raised ONLY by the daily-budget branch..."
```

This is the exact three-cause split the plan's §2 table states: the per-position ceiling raises a
**plain** `LiveTradingPermissionError`, indistinguishable by type from a dozen other refusal
paths (absent control, clock rewind, malformed value), while the daily-budget branch raises the
named subclass `DailyBudgetExhausted`. **CONFIRMED exactly, independent of round 1's and round
2's own re-derivations of the same fact** — this reviewer did not read those records' quoted line
numbers before re-deriving this from the file directly.

**The attribution design (three conjoined assertions for the per-position case: exact-type
discrimination, imported-constant reason-equality subject to a stated fallback, and the
differential) is therefore well-founded** — a plain `LiveTradingPermissionError` genuinely cannot
be attributed to the per-position ceiling by exception type alone, which is exactly why the
differential (the same order, same composition, same permit, denied at one ceiling and admitted
when only that ceiling moves) is load-bearing rather than decorative. No defect found in this
design; it is the correct response to a genuine ambiguity in the underlying exception hierarchy.

**The ADMIT/positive-control gating requirement (§8 item 3: "a denial transcript submitted
without [a green ADMIT] is not acceptance") — checked for the vacuous-pass risk this brief's
lens exists to catch.** Without a demonstrated success through the identical wiring, every one of
the five denial assertions could in principle be satisfied by a harness that denies everything for
an unrelated reason (a mis-wired fixture, a stale manifest path, a composition-construction
exception unrelated to either cap). The plan closes this with two independent guards — the ADMIT
case and the per-position differential — and neither is contingent on the other or on the
layer-B fallback. This is sound and, on this lens's third independent read, still finds no gap.

## Other claims re-verified

- `tests/unit/operator_control_env.py`'s docstring language ("exactly one path may [inject a
  value]... names no control... carries no value... restores in a `finally`") — read this session,
  matches the plan's quotation.
- The exit-side skip: `is_exit_side = order.side == OrderSide.SELL` and the guard `if not
  is_exit_side:` around `authorize_order_cost` — consistent with the plan's `:3520`/`:3522`
  citations (not re-derived line-by-line this session; substance already independently confirmed
  in round 2 by this reviewer and unchanged in this revision).
- `pm_us_crh_v4.json` presence under `deploy/families/` — confirmed present (unchanged carry
  forward).
- No cap value, magnitude, or real operator control is named, assigned, or implied anywhere in
  the plan text — re-scanned this session; confirmed.

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond the ±1-2 line citation
drift already disclosed and explicitly not scored as a defect in round 2 (no claim's substance
depends on the exact line, and re-anchoring would churn the document without changing any
assertion) — re-confirmed still true and still immaterial this round.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — closes G-16 exactly as stated; the
  three-cause correction (the plan's own round-1→round-2 fix) independently reproduces from source
  again this round and strengthens the closure rather than narrowing it.
- Technical correctness and evidence grounding: 20/20 — the exception hierarchy, the exact
  line-level cause split, and the attribution design were re-derived from source this session,
  independent of prior rounds' own text, and match exactly.
- Implementation specificity and feasibility: 15/15 — ten named tests in dependency order; the
  layer-B fallback has a stated, unambiguous pass/fail consequence and a forbidden repair (never
  touch the assignment scan); the synthetic-order bound is explicit with its structural reason
  (caps enforce at the exec-client boundary, independent of sizing, which is blocked on R-11).
- Acceptance criteria and validation quality: 20/20 — eight items; the ADMIT case structurally
  gates every denial's acceptance; the differential is a required transcript element, not
  optional; three `git diff`-empty guards plus the layer-B file-set check make "weaken a safety
  test to go green" mechanically detectable, satisfying this repo's binding constraint on that
  exact failure mode.
- Autonomous operation, failure handling, recovery: 15/15 — directly targets the unattended-spend
  bound; neither-control-set, boundary-admit, no-cost-on-refusal, and the latch-must-not-be-cleared
  rule are all pinned as named tests; correctly adds no new runtime control (this is a
  verification item, and the plan is honest that it detects a broken cap at test time, not at run
  time).
- Portfolio objective alignment, scope, dependencies: 10/10 — no cap value or magnitude is read,
  assigned, or implied; R-12 (session order-count ceiling) and sizing (G-11/MP-B, blocked on
  R-11) are correctly excluded to their own owners; test-only change, so rollback risk is nil.

**Total: 100/100**

## Required changes for full marks

None. No point was withheld without a nameable defect and required change; none could be named
this round, on a from-scratch re-derivation of the load-bearing exception-hierarchy claim this
brief specifically asked to be checked.

## Blockers

None named by the plan and none found independently. R-12 remains open and is explicitly and
correctly out of scope; this item creates no new ruling need and touches no operator-reserved
value.
