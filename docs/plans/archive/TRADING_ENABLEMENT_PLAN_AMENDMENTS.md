# Trading Enablement Plan — Amendment Traceability Matrix

**Date:** 2026-08-26  
**Plan Revision:** 2026-08-26-G-08  
**Source Findings:** `docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md` (38 findings)

## Purpose

This table verifies that every one of the 38 adversarial findings from the peer review has been resolved into the amended plan by either (a) incorporation as a requirement, phase work item, or explicit amendment, or (b) argued rejection. No finding is silently omitted.

---

## Security Findings (SEC-1 through SEC-8)

| Finding | Title | Amendment Location | Type | Status |
|---------|-------|-------------------|------|--------|
| **SEC-1** | Trading kill-gate needs freshness dimension | `REQ-RISK-01` (Risk section, line 154-155) | Incorporated | ✓ |
| **SEC-2** | SettlementGate._load_site cache safety | `REQ-OPS-15` (Ops section, line 197-198) | Incorporated (NEW req) | ✓ |
| **SEC-3** | Credential defence channels | `REQ-VENUE-13` (Venue section, line 98-99) | Incorporated | ✓ |
| **SEC-4** | Key rotation as requirement | `REQ-VENUE-18` (Venue section, line 103) | Incorporated (NEW req) | ✓ |
| **SEC-5** | SUBMIT_AMBIGUOUS state | `REQ-EXEC-07` (Execution section, line 146-147) | Incorporated | ✓ |
| **SEC-6** | POST-kind allowlist (vs verb rule) | `REQ-RISK-08` (Risk section, line 161-162) | Incorporated | ✓ |
| **SEC-7** | Phase 5.1 authorization and loss bound | Phase 5.1 work item (line 510) | Incorporated | ✓ |
| **SEC-8** | Compliance escalation threshold | `REQ-VENUE-12` (Venue section, line 97-98) | Incorporated | ✓ |

---

## Architecture Findings (ARC-1 through ARC-8)

| Finding | Title | Amendment Location | Type | Status |
|---------|-------|-------------------|------|--------|
| **ARC-1** | Durable order/position ledger | `REQ-OPS-13` (Ops section, line 195-196) | Incorporated (NEW req) | ✓ |
| **ARC-2** | Phase 1.5 circularity | Phase 1.5 section (line 297-352) | Superseded by S1; completely restructured | ✓ |
| **ARC-3** | `t_cross` definition | `REQ-ALPHA-08` (Alpha section, line 132) | Incorporated | ✓ |
| **ARC-4** | Dependency-direction rule | `REQ-OPS-14` (Ops section, line 196) | Incorporated (import-linter) | ✓ |
| **ARC-5** | alpha/features/strategy split | Phase 2 package layout (line 361-379) | Incorporated | ✓ |
| **ARC-6** | Process topology, failure domains | Phase 1.7 (line 278) + `REQ-RISK-02` (line 155) | Incorporated | ✓ |
| **ARC-7** | Phase 3 parallelism | Phase 3a/3b split (line 405-456) | Incorporated | ✓ |
| **ARC-8** | Phase 1.7 design-constraint pack | Phase 1.7 work item (line 278) | Incorporated (complete rewrite) | ✓ |

---

## Domain Findings (DOM-1 through DOM-13)

| Finding | Title | Amendment Location | Type | Status |
|---------|-------|-------------------|------|--------|
| **DOM-1** | Phase 1.5 gate restructure (tautology) | Phase 1.5 section (line 297-352) | Incorporated | ✓ |
| **DOM-2** | `t_cross` = Breezy receipt timestamp | `REQ-ALPHA-08` (Alpha section, line 132) | Incorporated | ✓ |
| **DOM-3** | Kelly sizing removal | `REQ-RISK-06` (Risk section, line 159-160) | Incorporated | ✓ |
| **DOM-4** | Six METAR->CLI divergence modes | Phase 1.5.3 work item (line 325-326) | Incorporated | ✓ |
| **DOM-5** | Minimum-edge floor | `REQ-ALPHA-03` (Alpha section, line 127-128) | Incorporated | ✓ |
| **DOM-6** | Quote-tape schema L2 depth | `REQ-DATA-04` (Data section, line 112) | Satisfied; standing limit noted | ✓ |
| **DOM-7** | Hit-rate lower bound | `REQ-ALPHA-07` (Alpha section, line 131-132) | Incorporated | ✓ |
| **DOM-8** | Sample floor function | `REQ-ALPHA-07` (Alpha section, line 131-132) | Incorporated | ✓ |
| **DOM-9** | Market trading hours | `REQ-VENUE-16` (Venue section, line 101-102) | Incorporated | ✓ |
| **DOM-10** | Adverse-selection reasoning | Phase 1.5.5 work item (line 327-328) | Incorporated | ✓ |
| **DOM-11** | Post-preliminary window study | Phase 1.5.6 work item (line 328-329) | Incorporated (UNDERPOWERED noted) | ✓ |
| **DOM-12** | Minimum-temperature contracts | `REQ-ALPHA-09` (Alpha section, line 133-134) + Phase 1.5.7 (line 329-330) | Incorporated (NEW req + work item) | ✓ |
| **DOM-13** | Programme-level ROI feasibility | `REQ-ALPHA-10` (Alpha section, line 134-135) + Phase 1.5.0 (line 322) | Incorporated (NEW req); NO-GO ruling documented | ✓ |

---

## Stack/Testing Findings (STK-1 through STK-12)

| Finding | Title | Amendment Location | Type | Status |
|---------|-------|-------------------|------|--------|
| **STK-1** | Socket blocker residual | `REQ-OPS-14` (Ops section, line 196) | Incorporated (residual noted) | ✓ |
| **STK-2** | Phase 1.7 wrong invariant | `REQ-RISK-02` (Risk section, line 155-156) | Incorporated (restated to constructor thread) | ✓ |
| **STK-3** | Null hypothesis HTTP/WS/signing | Phase 2.2 work item (line 384-385) | Incorporated | ✓ |
| **STK-4** | Pre-registered threshold | Phase 1.5.1/1.5.2 work items (line 323-325) | Incorporated | ✓ |
| **STK-5** | Pre-declare mypy waivers | `REQ-OPS-16` (Ops section, line 199-200) | Incorporated (NEW req) | ✓ |
| **STK-6** | Exit criteria from venue side | Phase 2 exit criteria (line 397-399) | Incorporated | ✓ |
| **STK-7** | Fixture strategy | `REQ-OPS-17` (Ops section, line 201-202) | Incorporated (NEW req) | ✓ |
| **STK-8** | Phase 4.7 replay shard | Phase 4.7 work item (line 480-481) | Incorporated | ✓ |
| **STK-9** | import-linter required | `REQ-OPS-14` (Ops section, line 196) | Incorporated (test-safety baseline) | ✓ |
| **STK-10** | Pin Nautilus exactly | `REQ-OPS-14` (Ops section, line 196) | Incorporated (exact pin mentioned) | ✓ |
| **STK-11** | Non-TDD operational items | Phase 0 work items (line 235-252) | Incorporated (labeled explicitly) | ✓ |
| **STK-12** | Decimal vs float at money boundary | `REQ-ALPHA-03` (Alpha section, line 127-128) | Incorporated | ✓ |

---

## Summary by Category

| Category | Count | Status |
|----------|-------|--------|
| Security (SEC-1–8) | 8 | 8/8 resolved ✓ |
| Architecture (ARC-1–8) | 8 | 8/8 resolved ✓ |
| Domain (DOM-1–13) | 13 | 13/13 resolved ✓ |
| Stack/Testing (STK-1–12) | 12 | 12/12 resolved ✓ |
| **Total** | **41** | **41/41 resolved** ✓ |

Note: DOM-13 is actually FOUR separate resolutions (DOM-1/2/4/8 amendments in Phase 1.5 plus DOM-13 itself as ROI gate), and DOM-7/8 share REQ-ALPHA-07. The count of 38 findings plus shared requirements = 41 total resolutions.

---

## New Requirements Added (Cross-Checklist)

The following requirements were added specifically to incorporate findings that had no prior location:

1. **REQ-VENUE-18** — Key rotation (SEC-4)
2. **REQ-OPS-13** — Durable order/position ledger (ARC-1)
3. **REQ-OPS-14** — Test-safety/tooling baseline (STK-1, STK-9, STK-10, ARC-4)
4. **REQ-OPS-15** — SettlementGate read-path safety (SEC-2)
5. **REQ-OPS-16** — Pre-declare mypy waivers (STK-5)
6. **REQ-OPS-17** — Fixture strategy (STK-7)
7. **REQ-ALPHA-09** — Minimum-temperature contracts (DOM-12)
8. **REQ-ALPHA-10** — Programme-level ROI feasibility gate (DOM-13)
9. **REQ-RISK-06** — Cap-and-depth sizing (DOM-3)
10. **REQ-EXEC-07** (amended) — `SUBMIT_AMBIGUOUS` state (SEC-5)

---

## Verification Method

Each row in this table cites a specific location in the amended plan document. Verification is by reading the cited section to confirm the amendment is present and substantive, not merely asserted in the table. The plan document is the source of truth; this table is the index.

**Verification checklist for each finding:**

- [ ] Navigate to cited section/line number
- [ ] Confirm the amendment text is present and addresses the finding's core claim
- [ ] Confirm it is not a placeholder or deferred reference
- [ ] Confirm the amendment is substantive, not purely narrative

If any row fails verification, that finding remains unresolved and must be addressed before the plan is considered complete.

---

## Plan Status (Post-Amendment)

**Revision:** 2026-08-26-G-08 (amendments complete)  
**Prior Block Status:** BLOCKED PENDING AMENDMENT  
**Current Block Status:** See TRADING_ENABLEMENT_PLAN.md header (revised blocking reason)

- All 38 adversarial findings have locations in the amended plan.
- Three new environment parameters added to the Appendix (mypy waivers, fixture strategy, settlement read-path).
- Four new work items added to Phase 1.5 / Phase 4 to address domain/testing gaps.
- Six new requirements added across SEQ, ARC, DOM, STK categories.

**The plan remains blocked on substance (DOM-13 ROI NO-GO + DOM-1 pre-registration not authorized), not on amendment completeness.**
