| Finding → resolution | Revised requirement |
|---|---|
| ARCHITECT 1 → remove surviving operator enablement | §3 explicitly replaces r2:63, r2:459 and r3:19, alongside the earlier restrictions. |
| ARCHITECT 2 → define all three caps | §10 replaces r2:409; MONTHLY-CAP delivery precedes any arm. |
| ARCHITECT 3 → identify ruling issuer | §6 assigns A1-class and FQ-v2 T2 rulings to the peer loop and replaces WB-10. |
| PREDICTION-MARKET 1 → restore α-draw timing | §5 draws shared-programme α at KC-n registration, after WB-4 passes and before promotion evaluation. |
| PREDICTION-MARKET 2 → restore partition/intake rules | §5 restores the confirmation dates, tested disjointness and new-KC-n intake requirement. |
| PREDICTION-MARKET 3 → exclude SEARCH efficacy | §§6/8 require confirmatory efficacy and name the SEARCH-only PASS + power PASS refusal test. |
| PREDICTION-MARKET 4 → prove monthly enforcement | §8 names the combined PM.us/Kalshi monthly-spend refusal test, including reboot seeds. |
| ARCHITECT LOW → correct readiness citation and remove extraneous text | §10 cites r2:408 (S11); omit approximate P4 dates and session/resume text. |
| PREDICTION-MARKET LOW → resolve timing, test and status wording | §7 preserves the frozen P4 trigger; §8 names independent permit withholding; status makes no approval claim. |

# K-2a/K-2b r5 delta — 2026-11-02
Status: revised plan addressing architect and prediction-market-reviewer findings; approval is not asserted.
Precedence: this delta **SUPERSEDES r4 ENTIRELY** and applies over r2 + r3; otherwise their requirements remain binding.
Citation aliases: r2 = `docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md`; r3 = `docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r3_delta.md`.

**§1 Objective / ROI.** Turn a prospectively proven Kalshi edge into bot-sized, authorized orders within portfolio caps; retire ineffective exposure automatically. Edge, fills and positive ROI remain unproven; preserve r3:24’s bounded build investment.

**§2 Dependencies.** GAP-6 `ADAPTER_DECISION: GO` authorizes building only. Before ARM, require delivered and verified OPERATOR-CONTROLS-MONTHLY-CAP, ROI-LEDGER decision access, SIZE-UNDER-CAPS r2 consumption and AUTO-PROMOTE-RETIRE r3 admission/actuation; dependency plan text alone is insufficient. Preserve adapter, admission, reconciliation and safety acceptance.

**§3 Explicit authority replacements; K-2a remains desk-only.** Apply the 2026-11-02 ruling recorded at `docs/core/PROGRESS.md:58`:

- r2:35: replace “two operator caps” with “three operator caps defined in §10.” r2:36: strike the blanket prohibition on K-2b enablement/permit integration; authorize only the reviewed shared integration below, preserving issuer and firewall protections.
- r2:63: replace “plus operator-only enablement (§10)” with “plus bot enablement via AUTO-PROMOTE-RETIRE r3”; both preceding rulings have the peer-loop issuer specified in §6.
- r2:318: replace the entire WB-10 handoff with §6’s sequence; no operator enablement remains.
- r2:365: replace the absolute actuation prohibition with shared supervisor actuation under AUTO-PROMOTE-RETIRE r3; family ARM cannot override global DISARM or revive retired PM.us.
- r2:406: replace “Operator-only (nothing else)” with “Operator decisions: three caps”; replace r2:408–410 entirely with §10.
- r2:459: replace “reserves only the caps and enablement” with “reserves only the three caps.” r3:13: strike its operator-only enablement sentence. r3:19: replace “§10 operator-only items” with “§10 as rewritten here; only the three cap values are operator decisions.”
- Amend r2:42–48 only for reviewed WB-9b shared node/supervisor, registry authorization, sandbox and pin changes required by this delta; other additions remain stop-and-replan.

**§4 Delivery order / ownership.** Builder follows r3:30’s WB order and inherited dependencies, then WB-8→WB-9a→WB-9b→WB-9c→WB-10; reviewers retain their named package responsibilities. Preserve N-S within seven days of GO, dated DEFER re-entry, r3:24’s ten-working-day/WP build bound and the shadow/parity requirements. GO never arms a family.

**§5 Registration / statistical isolation.** WB-7 produces only the SEARCH comparator and power result; REGISTERED permits registration, while UNDERPOWERED_NOT_REGISTERED follows N-2. Retain measured Kalshi inputs, climate-day dependence and shared programme totals/later PM.us allocation narrowing (r3:22–23,29,38; r2:482–486).
Any tail-band or STRATEGY-SEARCH candidate enters only as a **new KC-n via §5 class intake (FQ-R14)**. Freeze its PREREG, sizing policy, hashes and ONE look before any confirmatory-window read/run. Confirmation uses days **≥ max(2026-07-01, F_K)** and below F_H; **SEARCH ∩ confirmatory = ∅ is TESTED and any overlap blocks registration** (r2:496–498; r3:23).
The **shared-programme α draw happens at KC-n registration, after the WB-4 both-ledger test is green, and before AUTO-PROMOTE-RETIRE evaluates** (r3:38).

**§6 Efficacy / activation.** For r2:63,318,402, the **peer loop issues both the A1-class and FQ-v2 T2 rulings**, feeding AUTO-PROMOTE-RETIRE’s efficacy decision; these are no operator approval gate. WB-10 reads **“Look → FQ-v2 T2 + A1-class (peer loop) → AUTO-PROMOTE-RETIRE ACTIVATE.”** Efficacy evidence comes only from that KC-n’s confirmatory window: **a SEARCH-window PASS never satisfies the frozen efficacy rule**. Require frozen efficacy/financial guards AND with-guards power PASS AND valid three-cap authorization, then the reviewed registry/ACTIVATE/boot-permit route.

**§7 Sizing / lifecycle.** KC-n consumes SIZE-UNDER-CAPS `size()` directly; no operator q or proposal-only completion. Require one node/process and shared authorization across both venues, counting held/working exposure and durable reboot seeds once; recheck under the execution lock before submission. Preserve venue-bound permits, cross-venue family barriers and shared-city restrictions (r2:356–378). Global orders-off remains process-wide; family retirement preserves the other venue’s lawful reconciliation/exits. Use AUTO-PROMOTE-RETIRE’s restrictive/cancel/registry recovery with durable intent, applied/refused receipts and alert/outbox idempotency. P4 retirement belongs to that item; preserve its frozen D0/day-21 metadata without approximate calendar dates (`deploy/families/rulings/RULING_MAKER_sharp_v1_live_small_2026-10-21.md:23`).

**§8 RED-first acceptance tests — proposed names, required before implementation.**

- `test_search_only_pass_and_power_pass_refuses_to_arm`: SEARCH PASS + power PASS, with other gates satisfied but no confirmatory efficacy PASS, yields no ACTIVATE, permit or submission.
- `test_cross_venue_monthly_spend_with_reboot_seeds_refuses_over_cap`: each venue individually fits, but combined PM.us + Kalshi current-month spend plus candidate exceeds MONTH; include prior-day durable reboot seeds, duplicate replay and concurrent authorization; refuse before dispatch. Include exact-cap admission control.
- `test_family_permit_withholding_is_independent_across_venues`: parameterize the withheld/retired family; its permit remains denied while the other venue retains lawful operation/exits. Global DISARM denies both; Kalshi ARM cannot revive retired PM.us. Failure blocks WB-9b and triggers replanning, never another process.
- Also prove overlap blocks registration; α cannot draw before WB-4; GO/SEARCH/REGISTERED alone cannot arm; missing/invalid caps or efficacy/power refuses; qualified KC-n reaches a venue-bound permit; wrong-venue permits refuse; reboot cannot double-spend; cancellation and receipt/alert crash recovery are idempotent.

**§9 Pins / verification.** Review exact PREREG/manifest/sizing hashes, admission kinds, venue-permit contracts, node/supervisor/sandbox sets and affected closures. Preserve the single production issuer, Nautilus immutability, `allow_short=False`, Kelly ban, settlement/safety/contract/pin tests, holdout clauses 1–4, ONE look and NO-SEND predicates; widen exact expectations only (L-12). Use machine writers for evidence (L-75), the existing harness and only explicitly peer-authorized exceptions; never call `iem_cli_fetch.fetch`. Require focused cross-venue tests and import contracts, RED→GREEN→mutation-fails→restored-GREEN, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/kalshi-enable`; read actual EXIT. Security review covers shared actuation integration.

**§10 Operator decisions — replaces r2 §10 entirely.** Exactly three values: maximum USD spend per UTC DAY; maximum USD cost per POSITION, including held/working commitments; maximum cumulative USD spend per UTC calendar MONTH. Daily/monthly totals aggregate PM.us + Kalshi and survive reboot; profits/exits never refund gross spend. Apply MONTHLY-CAP’s cost unit consistently across venues, replacing r2:368 for cap accounting; fees still enter sizing/ROI. Read values only from gitignored `operator.env`; code and agents never assign, infer, default, raise or propose them. Missing/invalid values refuse ARM/entry; no two-cap fallback, extra venue cap, operator bankroll decision or operator quantity selection. Account eligibility/KYC, funding and credentials are external readiness facts (r2:408, S11), not additional strategy/enablement decisions. The bot decides everything else; engineering rulings belong to the peer loop.

Unverified:
- Codegraph (`projectPath=/home/jon/breezy`) and Sequential Thinking MCP tools were unavailable; documentary citations were read directly, but inherited code premises and proposed integration behavior lack the requested codegraph verification.
- No implementation, tests or runtime checks were performed; dependency delivery, monthly-history completeness, permit isolation and recovery remain acceptance obligations.
