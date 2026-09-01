# G-02 — Programme-level ROI feasibility arithmetic (DOM-13)

**Phase:** B (free falsification). **Blocks:** G-08. **Cost:** ~30 minutes.
**Can return NO-GO:** yes — and doing so is the point.

## Problem

DOM-13, verbatim from the adversarial domain review:

> No programme-level ROI feasibility arithmetic before committing to 63
> blocking requirements. Central estimate from the worked example is tens of
> dollars per day gross. 30 minutes of arithmetic, before Phase 1.5.1.

The programme is on the verge of committing to a large build — execution
client, settlement package, forecast model, risk system — on an edge whose
absolute dollar size has never been written down. If the ceiling is tens of
dollars per day gross, the arithmetic must be seen *before* the build, not
after.

## Approach

Bottom-up, from the requirements register's own worked example. Do not invent
favourable inputs; every input must be either measured, quoted from an existing
repo artifact, or explicitly labelled an assumption with its direction of bias.

1. Extract the worked example from `docs/plans/TRADING_ENABLEMENT_PLAN.md`
   (REQ-ALPHA / the two-tier gate sections) and restate its inputs.
2. Build the per-trade gross edge: entry price, size, and payoff at settlement.
3. Subtract costs in this order, each cited:
   - Venue fee. Formula `fee = theta * C * p * (1 - p)` is documented at
     `src/breezy/adapters/polymarket_us/parsing.py:28-49`, but the schedule is
     `[UNKNOWN]` — `maker_fee`/`taker_fee` are `Decimal(0)` and
     `assert_fee_schedule_known` is fail-closed. **Therefore theta must be
     treated as an unknown and the result presented as a sensitivity across a
     plausible theta range, not as a point estimate.** Flag the dependency on
     G-15 (fee schedule discovery) explicitly.
   - Slippage. Only measurable to level ten — the venue emits more levels than
     `OrderBookDepth10` retains (`book_open_510636.json` carries 12 bids /
     14 offers). State that bound.
   - Capital lock-up: the time between entry and settlement, which caps trades
     per day per market.
4. Multiply out: markets per day x cities x trades per market x net edge.
   Cities is at most five today, and DOM-9 warns it may be three — if market
   trading hours close before 17:00-19:00 ET, LAX and SFO are unreachable
   because their daily max occurs 14:00-16:00 local.
5. Produce three scenarios — pessimistic / central / optimistic — with the
   input that each is most sensitive to named.
6. Compare against a stated opportunity-cost floor for the remaining build.

## Deliverable

`docs/evidence/roi_feasibility_2026-08-26.md`, containing:

- Every input, with provenance (measured / quoted / assumed-with-bias).
- The three scenarios and the dominant sensitivity for each.
- A written GO / NO-GO / GO-CONDITIONAL determination.
- An explicit list of which numbers are unknown pending G-15 and DOM-9, and how
  much the verdict moves across their plausible range.

## GREEN criterion

The document exists, every number traces to a citation or a labelled
assumption, and the verdict is stated unambiguously. A NO-GO is a valid GREEN
outcome for this item — the item is "the arithmetic was done and reported",
not "the arithmetic was favourable".

## Risks

- **Motivated reasoning.** The largest risk is choosing inputs that produce a
  GO. Mitigation: label every assumption's direction of bias, and run the
  pessimistic scenario first.
- **False precision.** With theta unknown and the tape not yet started, this is
  an order-of-magnitude exercise. Present it as one. Do not report four
  significant figures off an unknown fee schedule.
