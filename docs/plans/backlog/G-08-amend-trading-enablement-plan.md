# G-08 — Amend TRADING_ENABLEMENT_PLAN with the full finding set

**Phase:** C. **Depends on:** G-01, G-02, G-03 (their determinations feed the
amendments). **Effect:** lifts the BLOCK ruling that currently gates Phase 2.

## Problem

`docs/plans/TRADING_ENABLEMENT_PLAN.md` carries the header **BLOCKED PENDING
AMENDMENT**. All four adversarial reviewers returned BLOCK. The ruling in
`docs/plans/TRADING_ENABLEMENT_REVIEW.md` is "Amend before implementation."
Phases 0 and 1 cleared; Phase 1.5 must be restructured.

Thirty-eight findings must be resolved into the plan: SEC-1..8, ARC-1..8,
DOM-1..13, STK-1..12.

## Approach

Work finding-by-finding. For each, the amended plan must either (a) incorporate
the fix, or (b) record an explicit, argued rejection. Silent omission is not an
option — the review is a standing record and an unaddressed finding will be
found again.

Grouped by what the amendment actually requires:

**Already closed by other backlog items — cite, do not re-do:**
- STK-1 -> G-04. STK-10 -> G-05. STK-6 -> G-06. STK-9 / ARC-4 -> G-07.
- DOM-6 (tape schema must carry L2 depth plus venue and receipt timestamps
  BEFORE Phase 1.1 records) — **already satisfied**: the recorder captures
  `OrderBookDepth10`. Note the standing limit that the venue emits more than
  ten levels and `DepthTruncation` records only how many were dropped.
- DOM-1 restructure -> feeds G-17's shape.
- DOM-11 -> G-01. DOM-13 -> G-02.

**Structural rewrites of the plan document:**
- ARC-2 superseded by cross-review synthesis S1 — record the supersession.
- ARC-5: collapse the arbitrary `alpha/` vs `features/` vs `strategy/` split.
  Three homes for one concern, with edge/fee/rounding math near-certain to be
  re-derived and drift. Pick one home and say which.
- ARC-7: split Phase 3 into 3a (genuinely parallel) and 3b (after Phase 2).
  3.3's alert denominator needs 2.4; 3.4 needs 4.1; 3.5/3.8 need venue
  settlement records.
- ARC-8: widen Phase 1.7 from a threading contract to a design-constraint pack
  covering durability/idempotency, fee-rate sourcing, the replay record-type
  constraint, and the `DataType` metadata trap.
- STK-11: several items have no natural RED test (all of Phase 0; the proposed
  mypy RED test requires deleting its own stub to go green). Restructure or
  label explicitly as non-TDD operational items.
- STK-8: shard the Phase 4.7 replay harness by `(city, climate-day)` with a
  per-run cap at config time. Including any weather record forces one-shot for
  the whole run, dragging ~100M quotes into memory.

**Requirements-register changes:**
- SEC-1: trading kill-gate needs a freshness dimension — OPEN **and**
  observation age within a required-no-default bound **and** a writer liveness
  heartbeat. Currently `_derive_state` is a pure read of latch booleans and an
  uncleanly-killed ingest process leaves the gate OPEN forever.
- SEC-6: REQ-RISK-08 (kill switch cancels working orders) and Phase 4.6 ("every
  POST path raises when the flag is unset") **contradict** — cancel is a POST,
  so clearing the enablement flag would disable the cancel path. Replace the
  verb rule with a POST-kind allowlist: cancel and read-only always permitted,
  exposure-increasing requests gated.
- SEC-5: add a `SUBMIT_AMBIGUOUS` state latching a per-market halt, plus
  fault injection in Phase 4. The hazard is not the retry, it is the ambiguous
  outcome.
- DOM-5: add a required-no-default minimum-edge floor. REQ-ALPHA-03's strict
  `>` currently permits trading at one basis point of edge.
- DOM-3: replace Kelly with cap-and-depth sizing on the measured lower bound,
  and ban `p = 1.0` from sizing math by test. Kelly is a category error at
  P=1 (f* = 1.0, nothing clamps).
- DOM-9: add market trading hours to the register. If trading closes before
  17:00-19:00 ET, Tier 1 is a three-city strategy, not five.
- DOM-12: add minimum-temperature contracts — the exact mirror, determined by
  ~08:00 local, shorter capital lock, every supporting requirement shared.
- DOM-2 / ARC-3: define `t_cross` as Breezy's own receipt timestamp, not the
  METAR valid time, which grants the analysis 5-45 minutes of information the
  strategy will not have.
- DOM-4: enumerate and price the six METAR->CLI divergence modes.
- DOM-7 / DOM-8: replace the tautological baseline with a hit-rate lower bound
  vs volume-weighted break-even, and make the sample floor a function of
  realized entry price.
- DOM-10: add adverse-selection reasoning.
- ARC-1: adopt native cache backing or specify a durable idempotency/order
  journal with a written recovery procedure. `cache.database=None` means every
  order-id link dies with the process, and `generate_missing_orders=True`
  SYNTHESIZES orders it cannot match.
- ARC-6: state process topology, failure domains, and restart-mid-position;
  resolve fail-fast-vs-hold-position explicitly. Also restate REQ-RISK-02 —
  the store confines to the CONSTRUCTING thread, not "the event-loop thread";
  those coincide today only by accident.
- SEC-2: specify the SettlementGate READ PATH, not just the call. A second
  reader caching the first result forever falsifies `require_open`'s own
  "never rely on an earlier decision" promise.
- SEC-3: close credential channels beyond `health.py` — httpx header logging at
  DEBUG (`BREEZY_LOG_LEVEL` is operator-settable), unscrubbed tracebacks, core
  dumps, key-file mode check (0600 is enforced for a health snapshot but not
  the private key), and a rule barring fixtures from loading a real key.
- SEC-4: promote key rotation from runbook bullet to requirement, and fix
  Phase 5.1 redaction to cover `X-PM-Access-Key`, not only the signature.
- SEC-7: give Phase 5.1 an authorization mechanism distinct from D4, and state
  the loss bound under the unmodelled interpretation — if the venue applies the
  price to the other leg, a 0.02 limit becomes 0.98 and the bound flips from
  `price*qty` to `(1-price)*qty`, up to 49x.
- SEC-8: widen the compliance escalation threshold beyond "only if it prohibits
  automated flow" — this is a CFTC DCM — and resolve that REQ-DATA-04 starts
  recording venue market data in Phase 1 before the terms governing storage and
  redistribution have been read.
- STK-5: pre-declare module-scoped mypy waivers. `strict = true` plus
  `disallow_subclassing_any` will reject `FeeModel`, `Strategy` and the live
  client subclasses on day one; the repo deliberately keeps waivers
  module-scoped rather than package-wide.
- STK-6 (second half): prove exit criteria from the VENUE side — fetch the
  account's order list and assert empty. Several current criteria are
  self-reported counters produced by the code under test, including "zero
  POSTs" and "zero safety-gate violations".
- STK-7: specify the fixture strategy — a loopback fake venue echoing raw
  header bytes (the `allow_socket` marker currently has zero users), contract
  tests over captured payloads, and slug property tests asserting REJECTION,
  not only round-trip. A round-trip-only property is satisfied by identity.
- STK-12: resolve `Decimal` vs `float` at the money boundary. `Price(0.51, 2)`
  accepts a float and rounds silently, and the strict-`>` edge comparison can
  return a different boolean in binary float than in `Decimal` — at the tick
  boundary, which is where the volume is.

## Deliverable

- Amended `docs/plans/TRADING_ENABLEMENT_PLAN.md`, revision bumped.
- A traceability table mapping all 38 finding IDs -> amendment location or
  argued rejection. No finding may be absent from the table.
- The BLOCK header replaced only when the table is complete.

## GREEN criterion

Every one of the 38 findings appears in the traceability table with a resolution
or an argued rejection, and an independent re-review confirms the mapping is
real rather than asserted.

## Risks

- **Paper compliance.** The failure mode is a table that cites a section which
  does not actually contain the fix. Mitigation: the re-review verifies by
  reading the cited section, not the table.
