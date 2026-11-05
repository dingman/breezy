| Finding → resolution | Binding r4 resolution |
|---|---|
| Architect 1: conflicting look instructions | “One look” governs S0 only; retain each family’s frozen sequential schedule (§5). |
| Architect 2: illegal P4 retirement | Reconcile actual state; CHAMPION uses HALT→RETIRE; absent row uses legal BOOTSTRAP→RETIRED (§4). |
| Architect 3: new disposition and persistence ordering | Add/test `RETIRED-EARLY`; ARM requires durable receipt+outbox; restrictive action never waits on either (§4). |
| Architect 4: promotion/activation mismatch | Enable exactly PROMOTE→CHAMPION and ACTIVATE after admission contracts; test pending-head/partner/activation sequence (§4). |
| Architect 5: unnamed veto and ordering | Persist family-halt latch before DISARM host actions; test the next RUNNING submit refuses (§4, §6). |
| Security 1: permit routing fails open | Route `None` unless positive, current ARM authorization verifies at boot; reverify before every entry (§4). |
| Security 2: caps and mint authority | Preserve boot mint; prohibit cap/session/order-ceiling assignments; #11 is a HARD build dependency (§2–§4). |
| Security 3: cancellation actor | Existing node path cancels owned orders; supervisor has no venue credentials or cancellation client (§4). |
| Security 4: supervisor authority | Exactly two actions, fixed allowlisted drop-in hashes, current CAS-head verification, protected unresolved submit intents (§4). |
| Security 5: receipt leakage/history | Closed typed receipt/outbox fields, leakage scan, append-only CAS, prospective bootstrap only (§4, §6). |
| Security 6: sandbox permissions | Decision row gains explicit intent writes; label command and binds remain byte-identical (§3). |
| Architect LOWs | Rechecked `PROGRESS.md:64`; require fresh P4 reconciliation, config invariant test, named sign-off owners (§4, §6). |
| Security LOWs | Void conflicting inherited ONE-look clauses; ARM never assigns `BREEZY_TRADING_ENABLED`; P4 follows verified legal transitions (§4–§5). |

# AUTO-PROMOTE-RETIRE — r4 delta
Status: DRAFT; sign-off owners: trading-bot-architect, prediction-market-reviewer, security-reviewer.
SUPERSEDES r3 ENTIRELY. Apply over r1+r2; this delta wins over conflicting inherited plans/review status.
All implementation contracts below are prospective requirements. U1–U4 identify reviewer-supplied code citations awaiting mandatory codegraph verification.

## 1 Objective + ROI mechanism
GOAL STATE: the bot promotes and arms qualified families, and halts/retires unproductive families, within the three operator caps.
WALK: frozen evidence → legal registry authorization → durable intent/receipt/outbox → constrained actuation → runtime confirmation.
Promotion removes the human execution bottleneck; retirement prevents further unproductive exposure. Neither establishes positive ROI.

## 2 Preconditions/dependencies
**HARD BUILD DEPENDENCY: backlog #11 monthly-cap implementation must land and pass its gates before this feature’s implementation begins, not merely before ARM.**
Require missing/invalid monthly-cap refusal, restart-safe accounting, and production entry enforcement alongside daily/position caps; no substitute session ceiling. Source: `docs/core/PROGRESS.md:59`.
Also require #4 ROI-LEDGER decision accessor, applicable GAP-4 registration/boundary inputs, sanctioned admission, and supported entry/cancel/reconciliation paths.
S0 must verify every code claim through `mcp__codegraph__codegraph_explore(projectPath="/home/jon/breezy")`; unresolved authorization, cancellation or transition semantics block delivery.
Engineering sign-offs are build gates; they introduce no per-event operator approval.

## 3 Scope and sandbox rows
Retain r1’s evaluator/decision-command scope; extend `app/trade.py`, the existing supervisor, registry admission/contracts, receipt schema, sandbox table and exact pin/allowlist tests.
Proposed intent directory: `<existing autonomy root>/actuation/intents/`; resolve and freeze its exact path at S0 through the existing paths abstraction.
| Row / actor | Required authority |
|---|---|
| Label command | Existing command and bind bytes unchanged; no new intent, registry or host-control writes. |
| Decision command | Separate ExecStartPost/sandbox row; read-only evidence; bounded existing registry/lock/demand/verdict/export writes plus explicit intent/outbox paths; no network, credentials or host control. |
| Supervisor reconciler | Read validated intents/registry; only fixed allowlisted deployment effects; no venue credentials or general command runner. |
| Trading node | Existing authenticated execution/cancellation path; owned-order scoping and reconciliation preserved. |
Add exact row/bind assertions and affected closure re-pins; do not append decision permissions to the label row [U4].

## 4 Steps, legal transitions and actuation
S0: implementer+reviewers freeze contracts, source citations, hashes, study inputs and acceptance before runs; measure resource fit and entry-withheld/hunt-window overlap.
S1–S3: retain r1+r2 registration, exact-prefix evaluation and durable decision production; add admission implementations and owner contract tests before enabling widening.
**Promotion:** new enabled widening set is exactly `{PROMOTE→CHAMPION, ACTIVATE}`. Use DAILY `PROMOTE(CHALLENGER→CHAMPION)` with the existing required partner/pending-head protocol, then PRELAUNCH `ACTIVATE(CHALLENGER→CHALLENGER)` referencing that pending pair; resolver effectiveness governs launch. Do not append ACTIVATE as a CHAMPION→CHAMPION event. Pin row states, partner links, fold results, masks and windows in an executable sequence test [U2–U3].
**Positive ARM authorization:** verify provisioned registry/demand directories, chain/head, effective CHAMPION plus valid ACTIVATE, family/policy/artifact bindings, current required pass evidence, no restrictive demand, no halt latch and no `venue_veto`.
At boot/restart, routed permit is **`None` unless all positive checks pass**; absence of a RETIRED demand never authorizes entry. Reverify authorization before every entry; stale, missing, unreadable, malformed, BAD_FILE or DIR_UNREADABLE inputs refuse [U1, U4].
Keep the existing boot issuance path as the only permit mint; no copied permit, alternate issuer or ceiling override. Preserve existing permit tests and add restrictive routing tests [U1].
**Supervisor enum:** exactly `ARM` and `DISARM`. Map each allowlisted family/action to a fixed destination and committed drop-in bytes/hash; DISARM restores the exact orders-off bytes. Freeze actual hashes before enabling execution; no runtime-generated content, supplied paths, shell fragments or arbitrary commands.
Before ARM effects, verify intent binding to the current registry CAS head/sequence and persist authorization receipt+durable alert/outbox. Recheck under the actuation lock immediately before effects; stale/forged/replayed intent cannot arm. Crash recovery revalidates before continuing.
Actuation may change only the allowlisted family selector and `orders_enabled_requested` through `BREEZY_ORDERS_ENABLED`; strategy-config `orders_enabled` stays False. Never assign `BREEZY_TRADING_ENABLED`, any operator cap, `BREEZY_MAX_SESSION_*`, or `BREEZY_MAX_ORDER_NOTIONAL_USD` [U1].
**DISARM ordering:** first durably set the family-halt latch consumed by `family_halt_submit_veto`, then restrictive demand/intent and legal registry effects; the latch precedes every DISARM host action. Receipt/outbox failure never delays these restrictions [U1].
The RUNNING node cancels through its existing owned-order path and reconciles zero owned rests; preserve exits and unresolved-intent reconciliation. Supervisor performs only allowlisted drop-in restoration, daemon-reload and controlled restart/relaunch.
Do not restart/relaunch across unresolved submit-intent latches. Keep entries vetoed and disposition DISARM-PENDING until cancellation, reconciliation and safe lifecycle conditions verify; never claim success from file restoration alone.
After safe reconciliation: verify exact drop-in/hash, reload, supervisor restart, node stop/DISPOSED and any orders-off relaunch before recording APPLIED. Rollback requirements: `deploy/families/rulings/RULING_MAKER_sharp_v1_live_small_2026-10-21.md:33`.
**P4 step 0:** freshly reconcile `pm_us_no_maker_sharp_v1` registry/runtime state. Recorded zero-fill evidence is `docs/core/PROGRESS.md:64`; it is not a fresh venue check.
CHAMPION: `HALT(CHAMPION→HALTED)` then `RETIRE(HALTED→RETIRED)`, both through DAILY. HALTED/SHADOW/CHALLENGER: legal RETIRE. Already RETIRED: reconcile idempotently. Absent row: only legal `BOOTSTRAP(None→RETIRED)` under BOOTSTRAP/genesis constraints; refusal leaves retirement pending and entries halted [U2].
Where a caller mask blocks an otherwise legal RETIRE, use the reviewed `OPERATOR_CLI` writer contract; never widen masks or bypass validation. Bootstrap never inserts retrospective deployment history or fabricates CHAMPION [U2–U3].
Add `RETIRED-EARLY` to the governed receipt schema/enum: inconclusive operational retirement, never statistical FAIL, look consumption or alpha spending. Preserve P4 PREREG and scheduled-stop metadata (`P4 ruling:23`).
**Closed actuation receipt/outbox fields:** `{schema_version, family_id, action, disposition, state, registry_head_sha256, policy_sha256, artefact_sha256, intent_sha256, dropin_sha256, created_at_ns, completed_at_ns}`; typed enums, validated identifiers/hashes, no extra fields or free text.
ARM requires durable authorization receipt+outbox before effects. APPLIED requires runtime confirmation; persistence failure blocks subsequent ARM progress. Restrictive receipts/outbox retry idempotently without reopening entry.
All registry writes remain append-only CAS; recover from durable state, never rewrite history. S4–S6 deliver runtime guards, constrained actuation, shadow proof and full gates; no live changes occur in this planning task.

## 5 Frozen acceptance / PASS–KILL
“One look” applies **only to the S0 power/replay study**. Void r3 item 5 entirely and inherited generic ONE-look wording wherever it would replace a family’s frozen trial schedule.
For the LD-OBF family retain registered looks every 10 admissible fills, chronological exact-prefix catch-up and terminal rules; no added looks, retrospective rescoring or efficacy hurdle.
Preserve r2 prefix-only financial guards, consumed blocked crossings, portfolio-wide LOSS_STOP, residual accounting, oldest-unsettled rules and SEARCH exclusions.
S0 PASS: with-guards power ≥0.75 and alternative early-retirement probability ≤0.10; otherwise KILL/BLOCKED-NEEDS-PLAN, without relaxation (`plan_r2_delta.md:9`).
ARM additionally requires frozen efficacy/financial qualification, S0 PASS, all three enforced caps and complete authorization/runtime gates. Unsupported paths remain BLOCKED.

## 6 RED-first tests and full gate
Prove eligible→pending PROMOTE/partner→ACTIVATE→boot mint→routed permit; every missing gate refuses. Test illegal CHAMPION ACTIVATE/direct RETIRE and all P4 branches.
Boot AND per-entry: missing/unreadable registry or directory, BAD_FILE, DIR_UNREADABLE, stale evidence, restrictive demand and venue veto refuse; positive control admits.
RUNNING node: halt latch precedes host calls; next submit after retirement refuses; existing node cancellation scopes ownership; unresolved submit intents prevent restart.
Fault-inject every persistence/effect boundary, CAS-head races, forged intents, drop-in hash drift, cancellation failure and receipt/outbox failure; retries never duplicate effects or weaken restriction.
Extend `test_operator_control_assignment_scan` for all three caps and prohibited overrides; assert no config `orders_enabled` or `BREEZY_TRADING_ENABLED` assignment.
Scan serialized receipts+alerts with planted order IDs, credentials and cap values; reject leakage, unknown fields and free-text payloads. Test RETIRED-EARLY never becomes statistical FAIL.
Test label command/binds byte identity, decision intent-write isolation, exact two-action enum, fixed hashes and restored `DROPIN_ALLOWLIST` row.
Require RED→GREEN→mutation-fails→restored-GREEN, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/auto-promote-retire`; inspect actual EXIT.

## 7 Pins/isolation/risks
Review exact admission/enabled-kind sets, engine/policy hashes, demand vocabulary, supervisor authority, drop-in rows and affected engine/label/health closures; no exemptions or weakened comparisons.
Every new cancellation-path callee joins the pinned NO-SEND callee set in a reviewed change. Preserve Nautilus, `allow_short=False`, safety/settlement/contract tests, holdout clauses and L-75; never call `iem_cli_fetch.fetch`.
Measure whole-unit resource use, restriction/cancellation latency and withheld trading hours; unproved resource fit or cancellation safety blocks delivery.

## 8 Operator decisions
Exactly three numbers: maximum USD per DAY, per POSITION and per MONTH, read only from gitignored `operator.env`; code/agents never assign, default, infer, raise or propose their values.
The bot decides sizing through #5, lifecycle, family selection and other actions through the backlog machinery; supersede inherited operator-only q/arming clauses (`docs/core/PROGRESS.md:58`).

## 9 Unverified citations / execution limits
- U1: `src/breezy/app/trade.py:576,1300,1464,1510`; `src/breezy/adapters/polymarket_us/safety.py:552`; `src/breezy/strategy/current_rung_hold/config.py:276`.
- U2: `src/breezy/persistence/autonomy/transitions.py:72,83,86,117,168`; `src/breezy/persistence/autonomy/fold_pairs.py:3`.
- U3: `src/breezy/persistence/autonomy/registry_store.py:466`; `src/breezy/persistence/autonomy/pins.py:14,61,125`.
- U4: `src/breezy/persistence/autonomy/demand.py:250`; `src/breezy/runtime/autonomy_sandbox/table.py:315`; `src/breezy/runtime/health_dropins.py:46`; `tests/unit/test_operator_control_assignment_scan.py:390`.
- Codegraph and Sequential Thinking tools were unavailable; mandatory code verification remains outstanding. Node cancel-chain details, hashes, runtime state, studies and tests remain unverified. No files were edited, created or staged; final git status was clean.
