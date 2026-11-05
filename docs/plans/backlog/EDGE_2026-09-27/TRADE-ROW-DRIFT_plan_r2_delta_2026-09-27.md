# TRADE-ROW-DRIFT plan r2: delta over r1 (BINDING; overrides r1 where they conflict)

Round-1 reviews, run blind:
- architect: REQUEST_CHANGES, 4 blocking items, with a ruling to include the R3 cross-check NOW.
- domain: ENDORSE-WITH-CHANGES, 4 required changes.

Both endorse option A. Coordinator merge follows.

## T-1. Diagnosable, delivered block (architect B1 + domain 2)
- **The block is permanent.** Completeness is EOF-only, so every pass re-reads the full history. One drifted row, even an old one, blocks every future retirement, and the OPEN intent blocks ALL orders. Record this in R1.
- **Add `first_reason: str` to `TradeRowScan`.** It holds the activity type plus the key NAMES of the first uninterpretable row, never values. It is built inside the pure function, which the firewall does not scan, and is logged in the caller's warning. Do not add a third `[k for k in page]` comprehension.
- **Delivery.** The block must surface through the EXISTING delivered path, the `open_intent_stale` CRITICAL, which carries `last_failure_kind`. The implementer:
  - verifies how `last_failure_kind` is set;
  - records a distinct failure kind naming the uninterpretable-row cause, using only already-permitted callees and state.
  - If that would need a new callee or an allowlist change: STOP and report. Never widen the firewall under this item.

## T-2. Include the R3 id cross-check now (architect ruling; supersedes the domain's "file as follow-up")
- **Uninterpretable:** a row where `aggressor.id` and `aggressorExecution.order.id` are both non-empty strings and differ. Same rule for the passive leg.
- **Ours:** a row where our id matches EITHER location. This only adds matches, so it can only add contradictions, never false retirements.
- **Absence is fine.** Do NOT require the execution block to be present.
- **Pre-landing check.** Confirm that all 17 MIA rows agree, via a one-off check against `PRIVATE_activities_types_trade.json`, run in a scratchpad, not committed. Report counts only; never print ids.
- **Test and mutant.** Add a test, plus mutant M17 (check removed).

## T-3. Simpler classification (architect item 2)
Drop the known-non-trade constant. The rule becomes:
- type is not `ACTIVITY_TYPE_TRADE` → flag ONLY if the row has a `trade` key or the type is missing / not a string;
- otherwise ignore.

## T-4. Tests and mutants
- **M14.** T1 adds `aggressor`-side drift (renamed aggressor with a well-formed foreign passive), plus int and `""` ids on BOTH legs.
- **M15.** T4 and T6 assert query count == 1, pinning the stop at the drifted page. This kills a `break` → `continue` mutant.
- **Past-day harness.** T4 runs on the PAST-DAY harness (≈4892/4996), where there is no holdings backstop (2818), AND on the same-day harness.
- **Self-trade test (domain 1).** Our id on both legs gives exactly one ref and `is_aggressor=True`, pinning the current semantics (`account_activity.py:411-419`).
- **M16 (domain 4).** An unmatched malformed row must not leak into `scan.refs`.
- **M5 retired** (see T-3).

## T-5. Risk register additions
- **R7 (fails DANGEROUS, accepted residual; domain 1).** A genuine fill re-tagged by the venue under a known non-trade type, without a `trade` key, is silently lost. This is structurally undetectable and belongs to the same class as R3's residue.
- **R1 wording.** The block is permanent; the mitigation is delivery via T-1.
- **F3 correction.** SFO execution ids are scrubbed, so id agreement is proven on MIA only.
- **Follow-up (non-blocking).** The probe's copy of the trade-row classification (`tests/unit/test_edge2_ambiguous_order_probe.py:88-95`) can drift from the resolver's. File it as PROBE-CLASSIFIER-DRIFT.

**Confidence after r2:** HIGH. The implementation review must confirm T-1 delivery without widening the firewall.

**Sequencing:** implement AFTER EDGE-2-REFACTOR step 0 merges. Both edit `tests/unit/test_current_rung_hold_ambiguous_resolver.py`.
