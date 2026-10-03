# AMBIG-LATCH-RESUME r3: merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| security-reviewer | 84 | NOT READY (1 HIGH) |
| trading-bot-architect | 84 | NOT READY (1 HIGH) |

## Verified OK by both reviewers

- No order can be admitted while an intent is unresolved:
  - `arm` refuses an OPEN or corrupt singleton (`submit_intent.py:403-409`);
  - `_trading_refusals` is checked first (`client.py:5357`), and `_intent_reconciled` comes before arm (`:5533`).
- The W window is bounded at about 11 s and is conservative.
- There is no double-order path.
- The F1/F3/F6 fixes are correct.
- The hard invariants are untouched.

## Owed in r4 (binding)

### CH1 [HIGH, both]: no-id AMBIGUOUS is reachable in steady state and needs the operator to clear

**Problem.**
- `client.py:5555-5569` creates a no-id AMBIGUOUS on any POST exception or timeout. `:5800-5828` does the same when a classified response has no venue id.
- r3's claim that this is a "strict subset of the W race" is false. Delete it.
- §2.7 itself shows 1 of 25 intents was OPERATOR_CLEARED.

**Coordinator ruling.** Option (a) is mandatory: an automated no-id resolver. Under the operator policy, nothing except the two caps may need an operator.

**Design floor.**
- Persist resolver context keyed by `client_order_id` at arm time, before the POST. That id is known pre-POST.
- After the minimum age (≥ `maxBlockTime` + margin, at least the existing 120 s), use complete reads only:
  - an eof-complete open-orders read;
  - an activities join by `client_order_id`;
  - the positions baseline.
- Outcomes:
  - **Found order or fill.** Adopt the venue id, take the with-id path, and send any fill through the existing accept-fill path. This covers the SIGTERM-mid-POST untracked-fill case (MED-2, architect).
  - **Nothing found in all complete reads, and the baseline is unchanged.** Retire the intent as a no-order outcome, using a zero-fill-style predicate.
  - **Anything contradictory or incomplete.** It stays AMBIGUOUS and pages CRITICAL. It is never retired on partial evidence.
- Verify against the existing resolver predicates (`client.py:2788-2980`) and the "GL-1 / R-7" rule: empty executions at `maxBlockTime` stay AMBIGUOUS unless the complete-read predicate holds.
- Quantify how often the no-id shape occurs, from the intent store's history: the shape of each of the 25, in particular the OPERATOR_CLEARED one.
- Rewrite R-NOID, goal 7, and row 4 of the clearing-path table.

### CM1 [MEDIUM, security]: the 16:40Z stop / 16:50Z refusal deadlock (L-48) for any OPEN intent

With CH1, show that the resolver retires the intent before the 16:50Z refusal on every resolvable path. Alternatively, for a resolvable intent, the supervisor runs the resolver, or relaunches, rather than refusing. Never require a hand step. Any residual unresolvable case is fail-closed and paged, and is named as residual with its bound.

### CM2 [MEDIUM]: the S5 CRITICAL for `no_context` must name the automated next action

That next action is the no-id resolver.

### CL1 [LOW]: T25(iii) pins the absence of an autonomous no-id path

Invert it into a positive test of the resolver, and disclose it as a ruled test change, like F2.

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
