# RULING — R-7 `PositionReportingLag`: keep and wire on the create path (2026-09-26)

**Authority.** `PROGRESS.md` R-7 (P7 §8), and `docs/plans/HYGIENE_FREE_FIXES_2026-09-12.md` §8 R-1, which deferred this decision to a strategy-lead ruling. This is that ruling.
**How it was ruled.** Two agents were briefed blind and separately:
- `trading-bot-architect` (AUTHOR): KEEP-AND-WIRE on the create path.
- `silent-failure-hunter` (ADVERSARIAL): keep, but only if the PREREG §11 row is corrected and a `tsEvent` validity guard is added.

The coordinator merged the two positions below. They did not contradict each other; the adversary's conditions are adopted in full.
**Status.** SIGNED 2026-09-26 (coordinator, under the operator standing grant; no operator-reserved value is involved).

## Question
Should `PositionReportingLag` (`src/breezy/runtime/position_reporting_lag.py`, which has zero producers and zero consumers) be kept and wired, or deleted?

## Evidence
- **Deleting it breaks a PREREG obligation.** `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:100` and `:264` name the first `PositionReportingLag` record as the verification of the `_REARM_MIN_DELAY_SECS = 120` floor.
- **§11 assigns emission to a path that cannot produce it.** `PREREG v3 §11` (`:230`) assigns emission to the **resolver path**. That is impossible as specified:
  - positions are read at `exec/client.py:1430` and `now_ns` is taken later, at `:1448`;
  - so the delta is negative, and `__post_init__` rejects it (`position_reporting_lag.py:60-66`);
  - the GET report has no venue fill instant (`exec/reports.py` refuses `insertTime`).

  The hygiene plan §1 ("second failure walk") says the same.
- **The create path does carry a venue-sourced fill instant.** `fill.ts_event` in the `KIND_ACCEPT_FILL` branch comes from `parse_fill_report`'s `transactTime`/`tsEvent`. The create path is also the population that is counted, because resolver fills are residual by PREREG.
- **Nothing native replaces it (L-1).** `position_check_interval_secs` polls; it does not measure fill→confirm lag. It is also contract-pinned to `None`.
- **Failure mode the adversary identified.** A venue `tsEvent` that is skewed in the same direction still passes the sign check and silently miscalibrates the 120 s floor. A missing `tsEvent` with a fallback to local `now_ns` would reintroduce poll-cadence contamination with nothing to mark it.

## Disposition: KEEP-AND-WIRE on the create-path accept-fill branch
Implement in this order, as a new backlog item **R-7-IMPL**. It needs a plan and peer review, because it touches `exec/client.py`.
1. **PREREG v3 Amendment A2 (docs only, lands first).**
   - Retarget the §11 `PositionReportingLag` row and the §13 floor-verification note from "resolver path" to "create-path accept-fill".
   - Append an A2 changelog entry that cites this ruling.
   - This is not a change to the estimand or the statistic. It corrects the instrument's location to the only path that can produce the quantity.
2. **Producer.** In the `KIND_ACCEPT_FILL` branch:
   - Remember `fill.ts_event`, keyed by instrument.
   - On the next eof-complete positions read showing the resulting LONG, construct the record with `first_eof_read_ts_showing_long` = that read's timestamp.
3. **`tsEvent` validity guard (adversary condition, binding).**
   - Emit only when the venue `tsEvent` is present.
   - Never fall back to local `now_ns`.
   - Reject values whose skew against the local receive time is outside a named constant bound, with a reason-coded log line. The bound is set by the R-7-IMPL plan, not invented here.
   - The record carries the `tsEvent` source field.
4. **Consumer.** At minimum, a structured log event tagged with the decision or cycle id. A durable sidecar for §13 floor verification is optional.
5. **Tests (RED first).**
   - Emission on accept-fill followed by a confirming read.
   - No record when `tsEvent` is absent.
   - Rejection of a skewed `tsEvent`.
   - The NO-SEND firewall guard stays unchanged. The module remains outside the egress-scanned `exec/` prefix.

## Consequences
- The `PROGRESS` R-7 row closes, and **R-7-IMPL** replaces it.
- Shipping the producer before Amendment A2 would contradict a BINDING spec, so the sequence above is mandatory.
- Until R-7-IMPL ships, the 120 s re-arm floor stays **unverified**, exactly as PREREG states today.
