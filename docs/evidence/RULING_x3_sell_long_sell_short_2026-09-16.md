# Ruling: `SELL_LONG`/`SELL_SHORT` and Barrier X3 (2026-09-16)

**Status: RULING -- no barrier change.** X3's token set (`BANNED_EXEC_DIRECTION_TOKENS`)
is left **byte-unchanged**. This document is an INC-E1 deliverable
(`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` §3, C5) that resolves a
question the plan's review raised as hypothetical -- it is not a request to
widen or narrow the barrier, and touches no test.

**Related:** CLAUDE.md Immutable Foundation (extension-only); plan
`POSITION_EXIT_EXECUTION_2026-09-16.md` Rev 2, §1 (R-THREAT/R-DEAD), §2
(PREREG v4), §3 (INC-E1/E2); prior ruling
`docs/evidence/RULING_x3_no_outcome_token_2026-09-14.md` (this document
follows its shape).

---

## 1. Current Barrier X3 (unchanged by this ruling)

**Module:** `src/breezy/adapters/polymarket_us/exec/submit_chain.py:1-6`
(docstring + module barrier).

**Enforcement:** `tests/unit/test_execution_egress_firewall_guard.py:251-258`
pins:

```python
BANNED_EXEC_DIRECTION_TOKENS = frozenset({"_SHORT", "BUY_SHORT", "SELL_"})
```

locked by a `RulePin` at `tests/unit/test_cage_rule_constants_are_pinned.py`.
Scope: any source under `src/breezy/adapters/polymarket_us/exec/` is
AST-scanned for these tokens.

## 2. The fact this ruling documents

`ORDER_INTENT_SELL_LONG` and `ORDER_INTENT_SELL_SHORT` are **DOCUMENTED**
venue tokens, not a hypothetical:

**Citation** (`docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_overview_2026-08-25.md`):

- `:95-97` -- the `intent` value table:

  | Value                     | Description                                  |
  | ------------------------- | --------------------------------------------- |
  | `ORDER_INTENT_SELL_LONG`  | Sell YES contracts (close long Yes position)  |
  | `ORDER_INTENT_BUY_SHORT`  | Buy NO contracts (go long on No outcome)      |
  | `ORDER_INTENT_SELL_SHORT` | Sell NO contracts (close long No position)    |

- `:114-121` -- the `outcomeSide` + `action` alternative table:

  | `outcomeSide`      | `action`            | Equivalent `intent`       |
  | ------------------ | ------------------- | -------------------------- |
  | `OUTCOME_SIDE_YES` | `ORDER_ACTION_SELL` | `ORDER_INTENT_SELL_LONG`  |
  | `OUTCOME_SIDE_NO`  | `ORDER_ACTION_SELL` | `ORDER_INTENT_SELL_SHORT` |

Both `SELL_LONG` and `SELL_SHORT` carry the X3-banned `SELL_` substring
verbatim. Today's live code only ever constructs a BUY
(`submit_chain.py:88-101,326-347`, `_ORDER_ACTION_BUY` hardcoded), so neither
token has ever appeared under `exec/` -- but a mid-day closing order
(INC-E2, position exit execution) is, by construction, always a SELL of the
held leg: YES-close is `SELL_LONG`, NO-close is `SELL_SHORT`.

## 3. Why this needs no X3 widening

X3 bans direction-inversion and short-sale tokens **specifically inside
`exec/`**, where the barrier's AST scan runs. `BUY_SHORT` is already
precedent for the correct resolution of exactly this collision: the NO leg's
own BUY intent (`ORDER_INTENT_BUY_SHORT`) also carries a banned substring
(`_SHORT`), and `RULING_x3_no_outcome_token_2026-09-14.md` did not widen X3
to admit it inside `exec/` -- instead, `leg_prices.py` (this repo's
declared classification/translation module, deliberately **outside**
`exec/`, per its own module docstring: "Lives OUTSIDE `exec/` deliberately")
is where the leg-to-venue-value mapping lives, and `submit_chain.py` never
needs the literal `BUY_SHORT` string in its own source.

The closing-order classifier for `SELL_LONG`/`SELL_SHORT` follows the same
precedent, and lives in the same module:

- **`adapters/polymarket_us/leg_prices.py`** already owns
  `VENUE_SIDE_FOR_LEG` / `VENUE_INTENT_FOR_LEG` (the BUY-path table,
  `:56-75` and neighbouring lines) and `assert_echo_matches_leg`
  (`:99-118`). INC-E2 adds a **sibling exit table** and
  `assert_exit_echo_matches_leg(leg, side, intent)` in this SAME module:
  YES-close -> `(ORDER_SIDE_SELL, ORDER_INTENT_SELL_LONG)`, NO-close ->
  `(ORDER_SIDE_SELL, ORDER_INTENT_SELL_SHORT)`.
- `submit_chain.py` gains `unmappable_exit_order_reason` and
  `build_exit_order_body` (INC-E2) that construct the wire body's
  `action`/`outcomeSide` fields (`ORDER_ACTION_SELL`, `OUTCOME_SIDE_YES` /
  `OUTCOME_SIDE_NO`) -- none of which is the literal string `SELL_LONG` or
  `SELL_SHORT`. The classifier that maps "close this leg" to those two
  venue-defined intent strings runs in `leg_prices.py`, where the mapping is
  read back to VALIDATE an echoed response, not authored as outbound text
  under `exec/`.

**Consequence: X3's token set is unchanged.** No new token needs banning
(the existing `SELL_` entry already covers `SELL_LONG`/`SELL_SHORT` as a
substring match, exactly as intended -- these tokens must never appear
under `exec/`), and no existing token needs removal (unlike the 2026-09-14
ruling, which removed `OUTCOME_SIDE_NO` because the live code needed to
construct it under `exec/`; here, the live code never constructs
`SELL_LONG`/`SELL_SHORT` text under `exec/` at all -- it constructs
`ORDER_ACTION_SELL` + `outcomeSide`, and only reads the two banned strings
back, from `leg_prices.py`, to validate a venue echo).

## 4. No new file under `exec/` (E0/N2 module table, unchanged)

Per plan §3 INC-E1/E2 (requirement, not preference): all exit-order mapping
functions land **inside the existing** `submit_chain.py` and `client.py`
under `exec/`; the response-side leg check
(`assert_exit_echo_matches_leg`) lands in the existing `leg_prices.py`,
outside `exec/`. `tests/unit/test_execution_egress_firewall_guard.py:739-765`
(the E0/N2 module table) is left untouched by this ruling and by INC-E1.

## 5. Sign-off

| Field | Value |
|-------|-------|
| **Barrier change:** | None -- `BANNED_EXEC_DIRECTION_TOKENS` stays `frozenset({"_SHORT", "BUY_SHORT", "SELL_"})` |
| **Fact documented:** | `ORDER_INTENT_SELL_LONG`/`ORDER_INTENT_SELL_SHORT` are DOCUMENTED venue tokens carrying the banned `SELL_` substring |
| **Resolution:** | Closing-order classification lives in `adapters/polymarket_us/leg_prices.py` (outside `exec/`), mirroring `BUY_SHORT`'s existing precedent |
| **Tests touched:** | None -- no firewall, cage-pin, or module-table test is edited by this ruling |
| **Related increment:** | INC-E2 (`build_exit_order_body`, `unmappable_exit_order_reason`, `assert_exit_echo_matches_leg`) -- not implemented by this document |
| **Date:** | 2026-09-16 |

---

**Generated: 2026-09-16 | Status: RULING -- no barrier change | Related plan:
POSITION_EXIT_EXECUTION_2026-09-16.md Rev 2, §3 INC-E1 (C5)**
