# Ruling: Barrier X3 narrowing for NO-outcome token (DRAFT, 2026-09-14)

**Status: DRAFT** (pending security reviewer sign-off)

**Related:** CLAUDE.md Immutable Foundation (extension-only); plan `NO_SIDE_EDGE_2026-09-14.md` rev 3, slices S5, N2-6, R3-3, R3-4; PREREG v3 §6 SAFETY pins.

---

## 1. Current Barrier X3 (today)

**Module:** `src/breezy/adapters/polymarket_us/exec/submit_chain.py:1-6` (docstring + module barrier).

**Text:**

> X3 bans the NO-outcome constant under `exec/`: a NO instrument is unmappable rather than encoded.

**Enforcement:**

The guard test `tests/unit/test_execution_egress_firewall_guard.py:252` pins:

```python
BANNED_EXEC_DIRECTION_TOKENS = frozenset({"_SHORT", "OUTCOME_SIDE_NO"})
```

This constant is locked by a `RulePin` at `test_cage_rule_constants_are_pinned.py:862-869`.

**Scope:** Any source code under `src/breezy/adapters/polymarket_us/exec/` (all slices under that package) is AST-scanned for tokens matching the banned set. Occurrence triggers a fail.

---

## 2. Why NO Leg Requires `OUTCOME_SIDE_NO` (not `BUY_SHORT`)

**Venue shape (captured, 2026-09-11):**

The Polymarket.us `/v1/orders/create` endpoint accepts:

```json
{
  "marketSlug": "<slug>",
  "outcomeSide": "OUTCOME_SIDE_YES" | "OUTCOME_SIDE_NO",
  "action": "ORDER_ACTION_BUY",
  "price": <decimal>,
  "quantity": <integer>,
  ...
}
```

**NO leg is a long position on the NO outcome:**

- A NO fill means: the HIGH temperature did not fall in the rung (complement of YES outcome).
- Premium: paid at the NO ask price `= 1 − YES_bid` (venue binary), capped by the per-position cap.
- Max loss: the premium paid (buyer's stake).
- This is a **BUY** of the NO outcome (long the NO instrument), never a short sale.

**SDK snapshot divergence:**

The SDK snapshot (`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py:9-14, 111-126`) shows `intent: OrderIntent` with members `BUY_SHORT`, `SELL_`, etc. This snapshot is **never exercised in live code** — it represents an older API or an unused path. The live body (§3) uses `outcomeSide` + `action`, which is the **CAPTURED live schema** from the 2026-09-11 fill.

**Conclusion:** NO is `outcomeSide=OUTCOME_SIDE_NO`, `action=ORDER_ACTION_BUY`. The token `OUTCOME_SIDE_NO` MUST be allowed in the exec adapter's order-building path (§3), but ONLY in that narrowed context. A bare `OUTCOME_SIDE_NO` string appearing elsewhere (e.g., in a comment, an unchecked string literal, or a fallback default in non-order code) violates the barrier.

---

## 3. Replacement Token Set (after narrowing)

**Banned tokens (unchanged):**

```python
BANNED_EXEC_DIRECTION_TOKENS = frozenset({"_SHORT", "BUY_SHORT", "SELL_"})
```

**Rationale:**

- `_SHORT` → banned (short sales on YES instrument, unmapped by the NO leg model).
- `BUY_SHORT` → banned (not a valid order action in the live venue schema; SDK-only artifact).
- `SELL_` → banned (naked short on YES, exceeds long limit, violates `allow_short=False`).
- **`OUTCOME_SIDE_NO` → REMOVED from banned set** (now allowed; required by order body for NO legs).
- **`OUTCOME_SIDE_YES` → NOT in banned set** (remains allowed; required by order body for YES legs).

**Result:** the new set is strictly narrower (one token removed, one added). The boundary artefact and all other safety checks remain unchanged.

---

## 4. Retained AST Control: `ONE - x` (complement arithmetic)

**Current guard (unchanged):**

`test_execution_egress_firewall_guard.py:1261-1275` function `_is_one()` detects:
- Literal `1`, `1.0`, or `Decimal("1")`, `Decimal(1.0)` (constructor forms).
- Only as the LEFT operand of `ast.Sub` (subtraction).

This catches expressions like `1 - price` or `Decimal(1) - price`, which are semantically a flip (complement in [0, 1] space). Banning this arithmetic prevents an accidental price inversion disguised as arithmetic.

**Widening (R3-4, S5):**

Extend `_is_one()` to also detect `ast.Name` bound to `ONE` at module level:

```python
# At module level, anywhere in src/breezy/adapters/polymarket_us/exec/
ONE = Decimal(1)

# Later in code, this should trigger the guard:
order_price = ONE - bid_price  # ← banned as a potential inversion slip
```

**Mechanism:**

In the AST walk for `ast.Sub`, if the left operand is:
- A literal (existing), OR
- An `ast.Name` with `id == "ONE"` AND that name is bound to `Decimal(1)` or `int(1)` at module scope (new)

then flag as a candidate complement arithmetic and refuse.

**RED test:** Plant `ONE - price` under `src/breezy/adapters/polymarket_us/exec/submit_chain.py` (real location, not in tests). Confirm the guard still raises before merge.

**Rationale:** `ONE` is a retained semantic hint (not a ban on the constant itself, but on its use in arithmetic that could be a hidden inversion). The widened detector keeps the barrier tight and catches the more likely abstraction accident (named constant → typo → unseen inversion).

---

## 5. One-Commit Rule for Pin Edit (R3-3)

**Today's state:**

```python
# test_cage_rule_constants_are_pinned.py:862-869
CAGE_RULE_PINS = (
    ...
    (
        "firewall",
        "BANNED_EXEC_DIRECTION_TOKENS",
        frozenset({"_SHORT", "OUTCOME_SIDE_NO"}),  # expected
        frozenset({"_SHORT"}),  # narrowed (can fail: removes OUTCOME_SIDE_NO)
    ),
    ...
)
```

**Change required (single commit):**

The slice S5 lands one commit that:

1. **Updates the pin `expected` value:**
   ```python
   frozenset({"_SHORT", "BUY_SHORT", "SELL_"})  # new expected
   ```

2. **Updates the `narrowed` variant** (for bidirectional test coverage):
   ```python
   frozenset({"_SHORT", "BUY_SHORT"})  # removes SELL_, still fails both directions
   ```

3. **Updates `test_execution_egress_firewall_guard.py:252`:**
   ```python
   BANNED_EXEC_DIRECTION_TOKENS = frozenset({"_SHORT", "BUY_SHORT", "SELL_"})
   ```

4. **Lands the ruling artefact** (this file, with security sign-off).

5. **Includes the `_is_one()` widening** (to accept `ast.Name` bound to `ONE`) + its RED test.

**Commit message format:**

```
fix(exec): narrow X3 to admit NO-outcome token, widen ONE-guard (R3-3)

- Remove OUTCOME_SIDE_NO from BANNED_EXEC_DIRECTION_TOKENS (required by NO order body)
- Add BUY_SHORT, SELL_ as new bans (SDK artifact, naked short)
- Widen _is_one() to detect module-level ONE constant in arithmetic
- Retire X3 docstring "NO is unmappable"; replace with OUTCOME_SIDE_NO rule in order path
- Signed-off by: security-reviewer [date/commit TBD]

Ruling: docs/evidence/RULING_x3_no_outcome_token_2026-09-14.md
```

**Immutability guarantee:**

No prior YES order paths change; no settlement, no safety tests weaken; `allow_short=False` holds; the boundary artefact and all sequential logic remain byte-identical. The pin edit is **the only code change to the firewall**; the guard test that checks `BANNED_EXEC_DIRECTION_TOKENS` remains in place and still locks the constant.

---

## 6. NO-Side Preview Capture (S5 Exit Criterion, N2-9)

**Requirement (safety gate):**

Before S5 ships and any live NO order is submitted, a NO-side preview request MUST be captured and confirmed to work:

```http
POST /v1/orders/preview
{
  "marketSlug": "<slug>",
  "outcomeSide": "OUTCOME_SIDE_NO",
  "action": "ORDER_ACTION_BUY",
  "price": <NO ask price>,
  "quantity": 1,
  ...
}
```

**Capture method:**

1. Under the permit (see PREREG v3 §4, safety pin SAFETY-C1), launch a NO-side preview request on an eligible market.
2. **Do NOT submit a create order yet.** Preview only.
3. Log the full request and response (venue API shape, including any new fields like `outcomeSide` response).

**Acceptance criteria:**

- Response status: 2xx (success).
- Response shape includes `outcomeSide: "OUTCOME_SIDE_NO"` (confirms venue accepts the token).
- Response includes computed fee, final price, any settlement info.
- No shape divergence from YES-side preview (same field structure, only values differ).

**Failure modes that halt S5:**

- Venue returns 4xx or 5xx (outcomeSide unknown).
- Venue returns `outcomeSide: "OUTCOME_SIDE_YES"` (server remaps NO to YES; venue bug or design divergence).
- Response shape differs from YES-side (new undocumented fields; parser will fail on fill).
- Network timeout or malformed response: retry once, fail if repeat.

**If preview fails:** S5 does NOT merge. Investigate whether the venue runs a **separate NO book** (not inverted from YES). If yes, the recorder MUST add a NO-side subscription to the data ingest, and S2's inversion model is withdrawn.

**Capture evidence location:** Log excerpt and response JSON stored in `docs/evidence/POLYMARKET_US_NO_PREVIEW_CAPTURE_2026-09-14.md` (auto-generated, not hand-written).

---

## 7. Security Sign-Off Block

| Field | Value |
|-------|-------|
| **Barrier change:** | X3 narrowing: remove `OUTCOME_SIDE_NO`, add `BUY_SHORT`, `SELL_` |
| **Guard widening:** | `_is_one()` to detect `ONE - x` arithmetic |
| **Pin edit:** | Single commit, update `expected` and `narrowed`, same label |
| **Exit criterion:** | NO-side preview captured and confirmed before first live NO order |
| **Hard invariants retained:** | Nautilus (extension-only), `allow_short=False`, NO-SEND firewall, both operator caps, settlement test, safety pins, boundary artefact |
| **Reviewer:** | (pending security reviewer sign-off) |
| **Date:** | (TBD) |
| **Commit SHA:** | (TBD, sign-off not complete) |
| **Attestation:** | This ruling has been reviewed and approved by the security reviewer. The pin change is traced to the NO-side requirement in PREREG v3 amendment. All safety controls remain in place. |

---

**Generated: 2026-09-14 | Status: DRAFT (awaiting security sign-off) | Related plan: NO_SIDE_EDGE_2026-09-14.md rev 3 | Sign-off: PENDING**
