# OQ-8 — Polymarket.us minimum taker fee: NONE, documented (2026-09-04)

Question (`docs/plans/EXEC_SPINE_2026-09-01.md` OQ-8): does the venue charge a minimum or
floor taker fee in absolute USD? Answer from `https://docs.polymarket.us/fees.md` (fetched
2026-09-04; word-for-word identical to `docs_snapshots/fees_2026-08-25.md`):

- **No minimum.** FAQ: "Can fees ever be zero? Yes. Fees are rounded to the nearest cent.
  On small trades (low quantity or prices near $0.00 or $1.00), the fee can round down to
  $0.00."
- **Rounding.** "All fees and rebates are rounded to the nearest $0.01 using banker's
  rounding (round half to even)." Example: "$0.025 rounds to $0.02, $0.035 rounds to $0.04."
- **Unit.** Per fill, with a one-directional per-order cap: "each fill is charged its
  banker's-rounded fee, adjusted so that the total commission collected across the order's
  fills never exceeds the banker's rounding of the cumulative exact fee. The adjustment can
  only reduce a fill's charge." At quantity 1 there is one fill and the cap is inert.
- **Closest venue example.** Fee schedule table, 100 contracts at $0.01 → $0.06; no
  1-contract example is published.

**Model.** `PolymarketUSFeeModel` (`src/breezy/adapters/polymarket_us/fees.py`) computes
`theta * qty * p * (1 - p)` and quantizes with `ROUND_HALF_EVEN` to the currency precision;
theta comes from the market's own `feeCoefficient` (never defaulted). Existing pins in
`tests/unit/test_polymarket_us_fee_model.py`:
`test_rounding_is_the_venue_documented_bankers_rounding_to_the_cent`,
`test_summing_per_fill_rounding_can_understate_the_venues_cumulative_cap` (asserts a $0.00
charge on a 1-contract fill).

**R-8 precondition ("a recorded `notional + max(pct, min)` bound").** SATISFIED from
documentation: `min = $0.00`; the per-fill taker charge at C=1 is bounded above by
`bankers(θ·p·(1−p))`, which is $0.02 at the maximum p=0.50 for θ=0.06. The bound must cite
the traded market's own `feeCoefficient`, not the docs' 0.06. A first real fill is still
required for R-8's separate MEASURED `commissionNotionalCollected` — a realized-return
requirement, not this precondition. **R-8-PRE-1 (a fixed-per-order cost term) is therefore
unnecessary**: the floor is zero and the existing model already expresses it; only pins for
1@0.01 → $0.00 and 1@0.50 → $0.02 are added.
