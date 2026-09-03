# Polymarket.us official-docs re-check — 2026-09-03

Scope: the four mechanics the 2026-08-25 snapshots left MISSING, plus a change
diff on fees / tick / minimum quantity. Source: docs.polymarket.us only
(Polymarket.us retail + trader guide). No polymarket.com / CLOB / Gamma source
used. Read-only fetches, no credentials, no orders. Fetched 2026-09-03.

## 1. Maximum order size — ANSWERED: none set by the venue

`/learn/trading/access-and-limits/trading-limits` — "Polymarket US does not
set trading size limits. You can place any order size, but it will only fill
if there are matching buy or sell orders at that price." The retail
create-order schema carries no max quantity/notional field (only
`maxBlockTime`). Size is therefore bounded by book depth and by OUR
operator-reserved per-position cap, never by the venue.

## 2. Implied probability and contract value — ANSWERED

`/getting-started/what-is-polymarket-us` — "A contract priced at 62¢ means the
market thinks there is roughly a 62% chance the event occurs"; contracts
"settle at $1 if the outcome happens, or $0 if it does not".
`/getting-started/glossary` — settlement $1.00 / $0.00.
`/concepts/orders` — YES and NO "always add up to $1.00".
`/fees` — the fee formula's price domain is "$0.01 to $0.99" (a fee-domain
statement, not an order-validation bound; the API reference's 0.01–0.99
range stands as the validation bound). Odds display is presentational only.

## 3. Retail idempotency / client order id — NOT DOCUMENTED

The retail create-order body has no `clientOrderId`, `clOrdId`, or
idempotency key: documented fields are marketSlug, type, price, quantity, tif,
participateDontInitiate, goodTillTime, intent, outcomeSide, action,
cashOrderQty, manualOrderIndicator, synchronousExecution, maxBlockTime,
slippageTolerance. The only ClOrdID mention (`/trader-guide/error-handling`,
"409 Conflict — Duplicate order with same ClOrdID") is institutional-side.
This confirms the EXEC SPINE premise (R-7 latch, `inflight_check_interval_ms=0`):
retail submission has no venue-side idempotency; the durable submit-intent
latch is the only guard against a double send.

## 4. Geographic / account / product restrictions — PARTIAL

- KYC required before deposit or trade (`/learn/get-started/signup`); name,
  date of birth, residential address; CFTC-regulated DCM/DCO.
- "Built for US residents" (`/getting-started/what-is-polymarket-us`).
- Participant restrictions: firms that interact with event contracts as a
  business, and holders of MNPI, should not trade
  (`/learn/trading/access-and-limits/trading-restrictions`).
- NOT DOCUMENTED: per-state eligibility, minimum age, excluded jurisdictions,
  retail API-key scoping. Pages checked: signup, account-under-review,
  trading-restrictions, trading-hours, general-faqs, welcome, api-reference
  introduction / authentication / rate-limits.

## 5. Change diff vs 2026-08-25 snapshots — NO CHANGE

Fees (`Fee = Θ × C × p × (1 − p)`, taker 0.06, maker rebate −0.0125,
effective 2026-07-01, rebate tiers), `minimumTradeQty` (0.01 example),
`orderPriceMinTickSize` (0.005 example) are unchanged. Changelog entries after
08-25 (v0.0.79–v0.0.82) are maintenance windows and sports market types only.

**Standing doc inconsistency (pre-existing, still live):** the learn page says
"does not support fractional contracts" while the API reference documents
decimal quantities where `minimumTradeQty < 1`. Resolve per market from the
`minimumTradeQty` field, never from the learn page.

## Consequences for the blocker register

- Max order size: no venue cap → no blocker; the per-position operator control
  is the only size ceiling.
- Idempotency: NOT AVAILABLE at the venue for retail → R-7 latch stays
  load-bearing (already built, zero call sites).
- Restrictions: state eligibility unverifiable from docs; the operator's
  completed KYC is the only evidence of eligibility.
