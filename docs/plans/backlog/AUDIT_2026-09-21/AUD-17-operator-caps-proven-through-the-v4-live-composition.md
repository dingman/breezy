# AUD-17 — Prove the two operator-reserved caps deny an order through the `pm_us_crh_v4` live composition

## 1. ID and actionable title

**AUD-17** — Establish, by test, that the maximum-daily-budget and maximum-per-position caps
actually refuse an order on the entry path **of the composition the node runs live**
(`pm_us_crh_v4`), that each denial is attributable to **its own** cap and not to an unrelated
upstream veto, that the composition can still **admit** an order (so no denial assertion passes
vacuously), and that the documented exit-side budget skip is exactly as documented — using the
repo's one whitelisted test-env seam and never a real operator value.

## 2. Source finding and class

- **Gap:** G-16 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:100-103`). Verdict
  **UNVERIFIED**: caps are enforced (agent-reported) but *"no test was identified that
  exercises them through the `pm_us_crh_v4` live composition."*
- **Class:** **verification gap.** The audit does not allege the caps are broken. It alleges we
  cannot show they hold on the composition that spends money.

**Evidence collected read-only for this plan, re-verified at HEAD (round 2) — and round 1's
enforcement map was WRONG in one respect, corrected below.**

**The entry path's denial causes inside `_submit_order`
(`src/breezy/adapters/polymarket_us/exec/client.py`). There are THREE, not two, and they are
distinguishable by exception TYPE only in part:**

| # | Gate | Call site | Raises | Caught at | Latches `_mark_budget_exhausted`? |
|---|---|---|---|---|---|
| 1 | Permit-derived **session notional** ceiling | `assert_live_order_submission_permitted(...)` `:3489-3496` | `SessionNotionalExhausted` (`safety.py:188`, extends `LiveTradingPermissionError` at `:184`) | `:3497` | **Yes** |
| 2 | Ledger **daily budget** | `self._ledger.authorize_order_cost(...)` `:3524-3528` | `DailyBudgetExhausted` (`operator_controls.py:126`, extends `LiveTradingPermissionError`) | `:3529` | **Yes** |
| 3 | Ledger **per-position cost** ceiling | the same `authorize_order_cost` call | **plain `LiveTradingPermissionError`** (`operator_controls.py`, the `if cost > position_cap:` branch) | `:3531` (the bare `except LiveTradingPermissionError`) | **No** |

**Round-1 correction, load-bearing for this plan's test design.** Round 1 described enforcement
point 1 as "the per-position cap". It is not. The per-position ceiling is cause **3**, and it
raises a **plain `LiveTradingPermissionError`** — deliberately, by an operator ruling recorded
verbatim in the source at `operator_controls.py:120-125`: *"raised ONLY by the daily-budget
branch … The per-position ceiling and the clock-rewind branch stay plain
`LiveTradingPermissionError` — neither means the day's dollar ceiling was reached."* Cause 1 is
a different ceiling entirely (the permit's session notional budget, derived at mint from the
two caps, `PROGRESS.md:17-24`, `safety.py:552-608`). **Pinning the per-position denial by
exception subclass is therefore impossible**, because plain `LiveTradingPermissionError` is
also raised by: an absent or malformed control, a rewound clock, and a dozen permit-validation
failures in `safety.py`. §6 solves this without naming a control.

All three denials converge on `_deny` (`exec/client.py:3293-3302`), which logs and emits
`OrderDenied` with `reason=f"{exc}; this client refuses to submit"`.

**The documented exit-side skip, verified verbatim in the same function's comment
(`:3508-3520`):** *"the daily budget is GROSS entry spend (§5.8) — an exit-side order never
calls `authorize_order_cost` and never debits the daily counter."* The branch is
`is_exit_side = order.side == OrderSide.SELL` (`:3520`), and `if not is_exit_side:` (`:3522`)
guards the `authorize_order_cost` call; `booking` stays `None` through every downstream
release/true-up site. The source also records that `is_exit_side` is equivalent by construction
to `is_exit_order`, because `submit_chain.unmappable_exit_order_reason` refuses any exit-tagged
order whose side is not SELL.

**Existing coverage, enumerated:**

| File | What it covers | Covers the v4 composition? |
|---|---|---|
| `tests/unit/test_operator_reserved_controls.py` (796 lines, ~50 tests) | The `DailySpendLedger` **mechanism** in depth: absence-refuses-everything, blank-is-absence, per-position cap boundary, day rollover, UTC boundary, booking release/true-up ordering, concurrency | **No** — mechanism-level, no composition |
| `tests/unit/test_polymarket_us_exec_client.py` | Drives `_submit_order`; imports `DailyBudgetExhausted`/`SessionNotionalExhausted` | Partially — exec-client level with a synthetic ledger, not the v4 family |
| `tests/unit/test_polymarket_us_permit_issuance.py` | Permit mint; bans every process-environ write from `src/`/`scripts/` | No |
| `tests/unit/test_operator_control_assignment_scan.py` (853 lines) | Four-layer proof that **nothing in the repo assigns** either control | No — and it must **stay green**, which constrains how AUD-17 may inject or assert anything |

`pm_us_crh_v4` is named in exactly three test files
(`test_trade_supervisor_phase1_unit.py`, `test_persistence_exit_gate.py`,
`test_family_registered_taker_fee_coefficient.py`) — **none of them a cap test.** G-16 is
confirmed: the mechanism is very well tested, the composition is not.

**The sanctioned injection seam — found, and it is the crux of this item.**
`tests/unit/operator_control_env.py`'s own docstring states it: *"A test must be able to DRIVE
the mechanism, which means putting a value in the environment for the length of one test.
**Exactly one path may do that — `tests/unit/operator_control_env.py`** — and it is whitelisted
from layer A only. It survives layer B because it never names a control… Every other route,
including a `monkeypatch.setenv` in any other test, fires."* The file itself is structurally
safe for three stated reasons: it names no control (the variable name is a **parameter**), it
carries no value (the value is the caller's argument, and the audit pins that the module holds
no non-empty string constant outside its docstrings), and both context managers restore in a
`finally`.

**This settles the plan's central risk before it is taken.** AUD-17's integration test must go
through `tests/unit/operator_control_env.py` and nothing else. A `monkeypatch.setenv` would
turn the assignment-scan suite RED, and the fix for *that* would be to weaken a safety test —
which is forbidden. **It also constrains ASSERTIONS, not just injection:** layer B compares the
set of files mentioning a control against an exact pinned set, so the new test file may not
contain either control's literal token anywhere — including inside an expected denial-reason
string (the per-position message embeds `MAX_POSITION_COST_USD_ENV_VAR`'s value). §6 handles
this by importing the constant and never spelling it.

## 3. Current behaviour, required behaviour, concrete gap

**Current.** The caps are enforced at three points inside `_submit_order`, and those points are
well covered in isolation. But nothing composes the live `pm_us_crh_v4` family and shows an
order it would otherwise have placed being denied by a cap. A refactor to composition — a
different exec-client factory, a veto reordering, an exit-tagging change — could silently move
an order around one of those gates and every existing test would stay green.

**Required.** An integration test file that builds the v4 composition as the node builds it,
drives a synthetic order through the entry path with synthetic caps in the test process, and
asserts **each denial attributably**, **an admit**, and **the exit-side skip**.

**Concrete gap.** Missing tests. **No `src/` change is expected**, and if one turns out to be
needed, that is a finding (the caps do *not* hold through the composition), not a licence to
adjust the enforcement to fit a test.

## 4. Priority, rationale, dependencies, execution order

**Priority: P1.**

Rationale: this is the only item in cluster E that guards **money**. The two caps are the
operator's entire control surface (`PROGRESS.md:17-24`, BINDING) and the sole bound on
unattended spend. Their enforcement is currently proven at the unit level and *assumed* at the
composition level. P1 also because the cost is low and the item is self-contained: it adds
tests to an existing, well-factored surface and is expected to change no production code.

It is P1 **despite** the bot not having traded since 09-15 — a control you only test when it is
about to be used is a control you test under time pressure.

**Dependencies.** None on any other AUD id. It does not depend on AUD-13 (reconciliation is not
on the submit path — though note `_submit_order` denies with `RECONCILE_NOT_RUN_REASON` at
`:3535` if `self._intent_reconciled is not True`, which is one of the upstream vetoes the
attributability assertions must exclude; see §6).

**Execution order:** 17a (enumerate existing coverage → close or confirm the gap) → 17b (the
integration tests, only if 17a finds the gap real).

**17a may close this item outright.** The brief's instruction stands: *if coverage exists, the
item closes with that evidence.* §2's enumeration strongly suggests it does not, but the
enumeration was by test-name and import; 17a must read the bodies.

## 5. Scope and explicit exclusions

**In scope:**
- **AUD-17a** — read the bodies of the four enumerated files and any composition/integration
  test, and produce a coverage determination with per-test citations.
- **AUD-17b** — if the gap is real: an integration test composing `pm_us_crh_v4` that proves
  (i) a per-position-cost denial, (ii) a daily-budget denial, (iii) a permit session-notional
  denial, (iv) a composition-level **ADMIT**, (v) the documented exit-side skip and its
  negative, and (vi) the neither-control-set refusal — all on the entry path.

**Explicitly excluded — these are hard boundaries, not preferences:**
- **Never assign a real operator value.** No cap value is written to any file, unit, `.env`,
  fixture default, or committed artefact. The test's values are synthetic, live only in the
  test process, and arrive only through `tests/unit/operator_control_env.py`.
- **Never weaken `test_operator_control_assignment_scan.py`.** All four layers must stay green
  unchanged. If the new test trips layer A or layer B, **the new test is wrong** — revise it,
  never the scan. In particular the new test file must not *name* either control anywhere,
  including inside an expected denial message.
- Never touch live-trading enablement, the permit mint site, `PERMIT_TTL_NS`, or the NO-SEND
  egress firewall.
- No change to `_submit_order`'s gate ordering, to `submit_chain.py`, or to
  `classify_create_order_outcome` (L-36, byte-unchanged pins).
- Not in scope: the permit's session ORDER-COUNT ceiling question — that is **R-12**, an open
  operator ruling (`PROGRESS.md:75`). AUD-17 tests the caps **as they behave today** and must
  not pre-empt R-12.
- **Not in scope: sizing and order construction.** `order_quantity=1` and MP-B's depth-capped
  sizing are G-11/MP-B, blocked on R-11. See §6's statement on the synthetic order — this
  exclusion is what makes that choice correct rather than a shortcut.

## 6. Proposed changes grounded in inspected code

**Native mechanism (null hypothesis, L-1).** None to extend. The enforcement sits in Breezy's
own exec client and `DailySpendLedger`; Nautilus's role is only that `_submit_order` is the
`LiveExecutionClient` coroutine the engine calls. Nothing is patched. The test composes through
Breezy's own composition entry point exactly as `app/trade.py` does.

**17b — test design.**

- **Location:** a new file under `tests/unit/` (the repo's composition tests live there:
  `test_current_rung_hold_composition.py`, `test_no_leg_composition_2026_09_14.py`,
  `test_app_trade_continuous_exit_manifest.py`). Name it for what it proves, e.g.
  `test_operator_caps_through_the_live_composition.py`.
- **Composition:** build the v4 family the way the node does — load
  `deploy/families/pm_us_crh_v4.json` via `load_family_manifest` and dispatch on its
  `composition_kind`, mirroring `app/trade.py:212-301`. **Load the shipped manifest, do not
  hand-write a fixture manifest** — a fixture would pass while the real family drifted, which
  is the exact failure mode G-16 describes.
- **The driven order is SYNTHETIC and hand-built, and that bound is correct.** The `Order`
  objects in these tests are constructed directly in the test (Nautilus order factory /
  test-order helpers, the same shape the existing
  `tests/unit/test_polymarket_us_exec_client.py` uses), **not** produced by the composed v4
  strategy's own decision path. This is deliberate for a reason that is structural, not
  convenient: the caps enforce at the **exec-client boundary** (`_submit_order`), downstream of
  and independent from sizing and the strategy's decision to trade at all. Making the strategy
  actually decide to submit would require driving a full market/observation fixture into the
  v4 decision path, whose sizing is G-11/MP-B and is **blocked on R-11** (§5) — so the test
  would be gated on an open ruling and would be measuring the strategy, not the cap. What must
  be real is the **wiring**: the shipped manifest, the real composition dispatch, the real
  exec-client factory, the real ledger, the real permit, and the real `_submit_order` gate
  ordering. The order object is the *input* to the thing under test, not part of it.
- **Cap injection:** `tests/unit/operator_control_env.py` only. It sets and restores in a
  `finally`; it never names a control and carries no value of its own. Values are synthetic and
  chosen to sit far from any plausible real figure.
- **Attributing a denial WITHOUT naming a control — the design point round 1 missed.** Because
  the per-position ceiling raises a plain `LiveTradingPermissionError` (§2 cause 3) shared with
  absence, clock-rewind and permit-validation failures, and because layer B forbids the test
  file from containing the control's token, attribution is established by **three conjoined
  assertions**, not by an exception name:
  1. **Type discrimination:** `type(exc) is LiveTradingPermissionError` — *exactly* that class,
     not a subclass. This excludes causes 1 and 2 positively.
  2. **Reason equality against a runtime-constructed string:** the expected `OrderDenied.reason`
     is built in the test from the constant **imported** from
     `breezy.adapters.polymarket_us.operator_controls` (`MAX_POSITION_COST_USD_ENV_VAR`), never
     from a literal, so the file contains no control token.
     **Which layer this actually has to satisfy — corrected this revision, because the previous
     answer was the wrong layer.** Layer B **cannot** object to this style, by construction, and
     that is not a tolerance that could change: `files_naming_a_control()`
     (`tests/unit/test_operator_control_assignment_scan.py``:347-358`) is a pure **byte census** whose needles are
     `CONTROL_ENV_VAR_NAMES` (`:90-92`) — the env-var NAME strings themselves — and the identifier
     `MAX_POSITION_COST_USD_ENV_VAR` does not contain `BREEZY_…` as a substring. Importing the
     constant and never spelling its value is precisely the design that makes the file invisible
     to layer B; that is the whole point of the style, not a risk to it.
     **The live constraint is layer A, and it is a real one.** `_mentions_control` (`:157-167`)
     classifies a bare `ast.Name` whose id is in `CONTROL_CONSTANT_IDENTIFIERS` (`:99-104`, built
     by reflection over `vars(operator_controls)`) as naming a control, and rule **A6**
     (`:285-295`) fires when such a name is handed to **any** callee outside
     `PERMITTED_CONTROL_ARGUMENT_CALLEES` (`:126-136`) or `_READER_CHAIN_CALLEES` (`:138`).
     `_mentions_control` uses `ast.walk`, so an identifier nested inside an f-string argument
     counts; and a new test file under `tests/unit/` is inside `SCAN_ROOTS` (`:86`) and is **not**
     in layer A's exempt set (`:321`, `whitelist | {DEFINITION_MODULE, SCAN_MODULE}`).
     **Consequence, binding on how the assertion is written:** it must take a **non-call** shape —
     a bare comparison, `assert denied.reason == f"…{MAX_POSITION_COST_USD_ENV_VAR}…"` — and the
     identifier must never be handed to `pytest.fail(...)`, to `pytest.raises(..., match=...)`, to
     `.format(...)`, or to any other call. The repo already pins that the comparison shape is
     clean: `test_the_scan_does_not_fire_on_asserting_about_a_control_name` (`:470-479`) plants
     exactly this form and asserts the scan does not fire. §7 17a step 2 confirms it empirically
     against the actual draft before 17b relies on it.
  3. **Differential (the decisive one):** the *same* synthetic order, the *same* composition,
     the *same* permit, with only the per-position ceiling raised — is **admitted**. A denial
     that disappears when exactly one control moves is attributable to that control by
     construction, and no upstream veto (PREREG, cell-legality, observation-ambiguity,
     `RECONCILE_NOT_RUN_REASON` at `:3535`, or the `submit_veto` at `:3485`) can produce that
     behaviour.
- **The six assertions, all scoped as deliverables (this is the §9-vs-§7/§8 inconsistency
  round 1 carried, now resolved: every requirement stated in §9 appears in §7's ordered steps
  and §8's acceptance count):**
  1. **Neither control set → every order denied.** The adversarial case that catches a
     composition which accidentally constructs a ledger with a default.
  2. **ADMIT / positive control.** With both controls set generously, the same synthetic order
     is **not** denied: no `OrderDenied` is emitted, `authorize_order_cost` returns a
     `SpendBooking`, and the flow proceeds to the point where a venue request would be made —
     under `run_tests_no_egress.sh`, so the request is structurally impossible to complete.
     **This is the falsifiability anchor: without it, all five denial assertions could pass on
     a harness that denies everything for an unrelated reason** (a mis-wired fixture, a stale
     manifest path, an exception during composition construction). It is scoped first in §7 for
     exactly that reason — nothing else is trustworthy until it is green.
  3. **Per-position cost denial**, attributed by the three conjoined assertions above.
  4. **Daily budget denial:** with the per-position ceiling generous and the synthetic daily
     budget nearly spent, the next entry order raises `DailyBudgetExhausted` — pinned **by
     class** — into `_deny`, and `_mark_budget_exhausted` latches (`:3530`).
  5. **Permit session-notional denial:** an order whose notional exceeds the permit's session
     ceiling raises `SessionNotionalExhausted` — pinned **by class** — at `:3497`, and
     `_mark_budget_exhausted` latches. This needs a second permit fixture (different mint
     parameters); that is a cost, not a design decision.
  6. **Exit-side skip and its negative:** an exit-side (`OrderSide.SELL`, exit-tagged) order
     does **not** call `authorize_order_cost`, leaves `booking is None`, and does not debit the
     daily counter — asserting the documented §5.8 GROSS-entry-spend semantics. Critically, the
     skip must be reachable **only** for an exit-tagged SELL: an untagged/naked-short order
     must not reach it (`allow_short` stays `False`;
     `submit_chain.unmappable_exit_order_reason` refuses any exit-tagged order whose side is
     not SELL, as the source comment at `:3515-3519` states).
- **Every denial assertion additionally asserts the absence of a venue POST.** The NO-SEND
  firewall constrains the callee set and the no-egress sandbox enforces it independently; the
  test asserts the absence directly so a future harness change cannot silently make "denied"
  mean "attempted and failed".

## 7. Ordered steps

**AUD-17a**
1. Read the bodies of `test_operator_reserved_controls.py`, `test_polymarket_us_exec_client.py`,
   `test_operator_control_assignment_scan.py`, `test_polymarket_us_permit_issuance.py`, and
   every `*composition*` test, and record per test: does it build the v4 family, and does it
   assert a cap denial on the entry path?
2. **Run BOTH layers against a scratch draft of the new test file and record both answers
   separately.** The question is not "layer B's tolerance" — that framing was wrong and is
   withdrawn (§6): layer B is a byte census over the env-var NAME strings and can never flag a
   file that only references the identifier. The two answers to record are:
   (i) `files_naming_a_control()` still returns exactly `{DEFINITION_MODULE,
   "operator.env.example"}` with the draft present — **expected green by construction**, recorded
   because §8 item 7 requires it, not because it is in doubt; and
   (ii) `scan_control_assignments()` returns `[]` with the draft present — **the answer that can
   genuinely go either way**, because layer A's rule A6 fires on the identifier handed to any
   unapproved callee (§6). Run both with the scratch file on disk and paste both outputs.
   **The response ladder, in order — the first rung is not "drop the assertion":**
   (a) if layer A fires, **rewrite the assertion into the clean non-call shape** §6 specifies (the
   shape ``tests/unit/test_operator_control_assignment_scan.py`:470-479` already pins as clean) — a test that
   trips the scan is a wrong test, and revising the test is the in-scope repair;
   (b) only if no in-scope shape is clean does assertion 3 (the differential) carry attribution
   alone and reason-equality get dropped;
   (c) **never the scan** — amending or weakening `tests/unit/test_operator_control_assignment_scan.py` to
   accommodate this test is forbidden (§5) under every branch.
   **The pass/fail consequence, stated rather than left to inference:** if the fallback triggers,
   the per-position denial test **still PASSES** on assertion 1 (exact-type discrimination,
   `type(exc) is LiveTradingPermissionError`) plus assertion 3 (the differential) alone. It is
   not skipped, not xfailed, and its acceptance status in §8 is unchanged — attribution survives
   because the differential is the assertion that excludes every upstream veto *by construction*
   (§9), and reason-equality was only ever corroboration on top of it. Two consequences bind
   either way: (a) the fallback must be **recorded in the transcript** with the scan output that
   forced it, so a future reader knows the test is running two-assertion rather than
   three-assertion; (b) dropping assertion 2 is the **only** permitted response — weakening or
   amending the assignment scan to accommodate the test is forbidden (§5), and a test that cannot
   be written without touching the scan is a wrong test, not a scan defect.
2a. **Add the precondition pin — retargeted this revision at the mechanism that can actually
   drift, and given an inversion mechanism that never touches the scan.** Revision 4 aimed this
   pin at layer B ("layer B still refuses the imported-constant style"), and that premise is
   **structurally false**: `files_naming_a_control()` (`:347-358`) censuses the env-var NAME
   bytes, so it never refused the identifier form and no in-repo event could make it start —
   short of editing the scan itself, which §5 forbids. A pin whose failure condition is
   unreachable is the vacuous-detector shape this plan refuses elsewhere; it is retargeted, not
   re-worded.
   **The pin, in the same new test file:**
   `test_layer_a_still_classifies_the_imported_constant_the_way_this_file_depends_on`. It asserts
   layer A's classification of the two shapes this file's assertion style turns on, by calling
   the scan's own public helper `find_control_assignments(path, source)` (`:224`) — which takes a
   **source string**, so both branches are exercised against **synthetic sources**, never against
   the repo:
   - **(a) the tolerance branch:** the bare-comparison shape §6 mandates
     (`assert denied.reason == f"…{MAX_POSITION_COST_USD_ENV_VAR}…"`) must return `[]`. If layer
     A's walk is later widened to scan comparison nodes, this branch fails, and its message names
     the action: *"layer A now flags the bare-comparison form — rewrite the per-position
     reason-equality assertion or drop it; never amend the scan."*
   - **(b) the intolerance branch:** the same identifier handed to an unapproved callee must
     return a non-empty list carrying rule **`A6`**. If `PERMITTED_CONTROL_ARGUMENT_CALLEES`
     (`:126-136`), `_READER_CHAIN_CALLEES` (`:138`) or `_mentions_control` (`:157-167`) is later
     widened so A6 stops firing, this branch fails, and its message names the action: *"layer A no
     longer constrains the assertion's shape — re-read §6 before relying on the old constraint,
     and if reason-equality was ever dropped, restore it."*
   **How the pin is demonstrated capable of failing WITHOUT editing the scan — the round-4
   requirement, answered by mechanism rather than by assertion.** Branch (b) **is** a live firing
   of layer A, produced in-test from a synthetic source string; the RED→GREEN evidence for
   "capable of firing" is that same helper returning `[]` for branch (a)'s source and an `A6`
   `Assignment` for branch (b)'s, in one run. No monkeypatch of `files_naming_a_control`, no
   temporary edit, and nothing to revert: this is the repo's **own** established idiom for
   proving the scan non-vacuous — `test_the_scan_fires_on_every_planted_assignment_form`
   (`:452-455`) and `test_the_scan_does_not_fire_on_asserting_about_a_control_name` (`:470-479`)
   both feed `find_control_assignments` a planted source string for exactly this purpose. `git
   diff` on `tests/unit/test_operator_control_assignment_scan.py` stays empty (§8 item 5, unchanged).
   **Three bindings:**
   (i) the pin **calls** the scan's helpers and never modifies, copies or re-implements them;
   (ii) the pin's own source must not trip layer A on itself — its synthetic sources are plain
   string constants (never equal to a control NAME, so `_mentions_control` is False on them) and
   the only call carrying them is `find_control_assignments`, whose arguments name no control;
   (iii) `@pytest.mark.xfail(strict=True)` remains the rejected alternative, for the reason §9
   gives.
   **It is written on both paths, not only on the fallback path.** Revision 4 created it only if
   the fallback triggered; with the target corrected, the drift it guards — layer A's scope —
   bears on the assertion whether that assertion is **kept** (branch (a) is the premise that keeps
   it legal) or **dropped** (branch (b) is the premise that justified dropping it). Conditioning
   it on the fallback would leave the expected path — assertion 2 retained — unguarded, which is
   the durable-by-default shape round 3 raised in the first place.
3. Re-verify the note at `test_operator_reserved_controls.py:708`
   (`test_the_mechanism_has_no_production_call_site_yet`) against HEAD. Disposition **AM-3** of
   `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:152` records that a sibling claim of "no
   production call site" was measured FALSE (`factories.py:777` constructs `DailySpendLedger`
   and the live submit path calls `authorize_order_cost`/`release_booking`/`true_up_booking`).
   **Determine which mechanism that test actually pins** — if it pins the ledger itself, it is
   asserting something the audit shows to be false and that is a finding in its own right; if
   it pins `seed_spent` or another helper, it is fine. Report the answer either way.
4. Write the determination. **If coverage exists, the item CLOSES here with that evidence and
   17b is not built.**

**AUD-17b (only if the gap is real; RED first)**
1. RED: **the ADMIT / positive control** —
   `test_the_live_composition_admits_an_order_when_both_controls_are_generous`. First, because
   it proves the harness can produce a success through this exact wiring; every later denial
   assertion is falsifiable only against it.
2. RED: `test_every_order_is_refused_when_neither_control_is_set`.
3. RED: `test_a_cost_above_the_per_position_ceiling_is_denied_by_that_ceiling_specifically` —
   including the type-discrimination, reason-equality (subject to §7 17a step 2) and
   **differential** sub-assertions, the differential being the same order admitted when only
   that ceiling is raised.
4. RED: `test_an_order_past_the_daily_budget_raises_daily_budget_exhausted_and_latches`.
5. RED: `test_an_order_past_the_permit_session_notional_raises_session_notional_exhausted_and_
   latches` (second permit fixture).
6. RED: `test_an_exit_tagged_sell_skips_the_daily_budget_and_leaves_no_booking` and its
   negative `test_an_untagged_sell_never_reaches_the_exit_side_skip`.
7. RED (boundary, at composition level rather than by reference to the mechanism suite):
   `test_a_cost_exactly_at_the_per_position_ceiling_is_admitted_through_the_composition` and
   `test_spend_exactly_at_the_daily_budget_is_admitted_through_the_composition`, plus
   `test_a_refused_order_leaves_the_daily_counter_unchanged`.
8. GREEN: **expected to be green on arrival** — these are characterisation tests over behaviour
   that should already hold. If any is genuinely RED, **stop and report**: a cap that does not
   hold through the live composition is an incident, not a task.
9. Run `test_operator_control_assignment_scan.py` and `test_polymarket_us_permit_issuance.py`
   explicitly and show them green **unchanged** (`git diff` empty for both).
10. `lint-imports` + `mypy`, then the full gate `scripts/ci/run_tests_no_egress.sh` (addopts
    already carries `-q`; never add `-q`).

## 8. Acceptance criteria and required evidence

1. A coverage determination citing each inspected test by `file::name`, and a one-line verdict
   on whether the gap is real.
2. A recorded answer to §7 17a step 2 (layer B's tolerance for the imported-constant assertion
   style), and a stated answer on `test_operator_reserved_controls.py:708` vs disposition AM-3.
2a. **The precondition pin from §7 17a step 2a exists and is green on BOTH paths** (it is no
   longer conditional on the fallback), and its transcript shows **both branches exercised in one
   run**: the bare-comparison source returning `[]` and the unapproved-callee source returning a
   non-empty list carrying rule `A6`. **That two-branch output IS the "capable of firing"
   demonstration** — branch (b) is a live firing of layer A against a synthetic source, produced
   through the scan's own public `find_control_assignments(path, source)` helper, so the
   demonstration requires **no** edit to `tests/unit/test_operator_control_assignment_scan.py` and **no**
   monkeypatch of it; §8 item 5's empty `git diff` on that file is unaffected and must still hold
   in the same transcript. A pin whose firing could only be shown by editing the scan would be
   unacceptable on both counts (it would breach §5 during execution, and a pin that cannot fire is
   the vacuous-detector shape this plan refuses elsewhere). The transcript also records which rung
   of §7 step 2's response ladder was taken — assertion 2 kept in the clean shape, rewritten, or
   dropped — so a later reader knows whether the per-position test runs three-assertion or two.
3. If 17b is built: RED→GREEN (or green-on-arrival, explicitly stated as characterisation)
   transcripts for **all ten named tests** in §7 — the six assertions of §6 plus the three
   boundary/no-cost-on-refusal cases and the exit-side negative. **The ADMIT case must be green
   before any denial case is accepted as evidence**; a denial transcript submitted without it
   is not acceptance.
4. For the per-position case: the transcript must show all available attribution
   sub-assertions, and **the differential explicitly** — the same order, same composition,
   denied at one ceiling and admitted at another.
5. `git diff` proving **zero** changes to `test_operator_control_assignment_scan.py`,
   `test_polymarket_us_permit_issuance.py`, and `test_operator_reserved_controls.py`, and both
   suites green.
6. `git diff` proving zero changes under `src/` — or, if a change proved necessary, an explicit
   incident note explaining why the caps did not hold through the composition.
7. A grep proving **no committed file gained a cap value**, and that the assignment scan's
   layer-B mentioning-file set is unchanged (i.e. the new test file is not in it).
8. Full gate `scripts/ci/run_tests_no_egress.sh` green; `lint-imports` + `mypy` clean.

## 9. Validation

**Failure cases the tests must cover — every one is scoped as a deliverable in §7 and counted
in §8 item 3. (Round 1 stated these here without scoping them; that inconsistency is resolved.)**

| Case | §7 step | §8 coverage |
|---|---|---|
| Neither control set → every order denied | 17b.2 | item 3 |
| One control set → still denied | 17b.2 (same test, parametrised) | item 3 |
| Cost exactly at the per-position ceiling → **admitted** | 17b.7 | item 3 |
| Spend exactly at the daily budget → **admitted** | 17b.7 | item 3 |
| A denial never consumes budget | 17b.7 | item 3 |
| Both controls generous → **admitted** (positive control) | 17b.1 | item 3, gating |

**Vacuity is the named risk and it is closed structurally.** Without the ADMIT case, every
denial assertion would be satisfiable by a harness that denies everything for an unrelated
reason. Two independent guards now exist: the ADMIT case (a success must be producible through
this exact wiring) and the per-position **differential** (a denial that vanishes when exactly
one ceiling moves cannot have come from an upstream veto). Either alone would leave a hole;
together they make each denial both falsifiable and attributable.

**This is also why the §7 17a step 2 fallback costs the test nothing — and why it is now
expected NOT to be reached.** Reason-equality (assertion 2) is the *weakest* of the three: it
corroborates a cause the differential already establishes structurally. If layer A flags the
draft's assertion shape and no clean in-scope shape can be found, the per-position test runs on
exact-type discrimination plus the differential and **still passes and still counts as
acceptance** — no guard is lost, because neither of the two guards named above is assertion 2.
What would genuinely gut the test is losing the differential or the ADMIT case, and neither is
contingent on any layer of the scan. **The layer the fallback hangs on is corrected this
revision:** it was written as layer B's tolerance, which is not a variable at all — layer B is a
byte census over the env-var NAME strings and never saw the identifier form (§6). The only layer
that can refuse this assertion is **layer A**, via rule A6 on an identifier handed to an
unapproved callee, and the first response to that is to rewrite the assertion into the non-call
shape the scan's own `test_the_scan_does_not_fire_on_asserting_about_a_control_name` (`:470-479`)
already pins as clean — not to drop it.

**And the pin that guards this must itself be capable of failing, which the round-4 version was
not.** The round-3 residual (a decision that becomes permanent by accident) is real, and the
mechanism (§7 17a step 2a) is a **precondition pin**, not an `xfail`:
`@pytest.mark.xfail(strict=True)` on a restored three-assertion variant remains **rejected**,
because the scan's classification does not manifest as a failure of *this* test at all — it
manifests in the scan's own verdict, so the new test would XPASS under both classifications and
`strict=True` would fire on the wrong signal. But the revision-4 pin asserted a premise — "layer
B still refuses the imported-constant style" — that **cannot stop holding**, because
`files_naming_a_control()` (`:347-358`) compares bytes against `CONTROL_ENV_VAR_NAMES` (`:90-92`)
and the identifier does not contain the env-var name as a substring. A premise that cannot change
gives a pin that cannot fail, and the only way to show it failing would have been to edit the scan
— the one repair §5 forbids. The pin is therefore **retargeted at layer A**, whose scope genuinely
can widen or narrow under ordinary maintenance of `tests/unit/test_operator_control_assignment_scan.py` for
reasons unrelated to this test — which is exactly the drift a pin should catch — and it asserts
**both** directions of that scope (the comparison form tolerated, the unapproved-callee form
flagged as `A6`) by feeding **synthetic source strings** to the scan's own public
`find_control_assignments(path, source)` (`:224`). That makes the "capable of firing"
demonstration intrinsic: the intolerance branch *is* a firing, in the same run, with no
monkeypatch and no edit, using the repo's established planted-source idiom (`:452-455`,
`:470-479`). Each branch's failure message carries its own restoration instruction, so the finder
does not have to reconstruct why an assertion was kept or dropped rounds earlier.

**Integration behaviour.** The test drives the real composition and the real `_submit_order`
ordering: `submit_veto` (`:3485`) → `assert_live_order_submission_permitted` (`:3489`) →
exit-side branch (`:3520-3522`) → `authorize_order_cost` (`:3524`) → reconcile check (`:3535`)
→ intent latch. **It must not stub any of those gates**, because the gate *ordering* is part of
what is being proven — a cap checked after the venue POST is not a cap. The upstream gates that
can deny for non-cap reasons (`submit_veto`, `RECONCILE_NOT_RUN_REASON`) must be configured to
PASS in the cap tests, and that configuration is itself asserted by the ADMIT case.

**Autonomous operation.** These caps are what bound unattended spend across a 10 h permit and a
nightly relaunch. The node runs unsupervised; the caps are the only thing between a
mis-specified family and the daily budget. This item does not add a control — it proves the
control is wired to the thing that actually places orders, and that the proof cannot pass
vacuously. **No recovery behaviour is added or changed:** a latched `_mark_budget_exhausted`
(causes 1 and 2) persists by design and this item must not clear, shorten or test around it.

**Egress.** The test runs under `scripts/ci/run_tests_no_egress.sh`. No venue request may be
made; the denial assertions include the *absence* of a POST, which the no-egress sandbox
independently enforces, and the ADMIT case asserts the flow reaches the request boundary
without crossing it.

## 10. Deployment, observability, rollback

- Test-only. No deploy, no unit, no env, no runtime behaviour change, nothing to observe in
  production.
- Rollback: delete the new test file. Since no production code changes, rollback risk is zero —
  which is itself an argument for the P1 rating.
- **If 17b turns up a genuine RED**, the resulting fix is a *different*, escalated item with its
  own plan; do not fold a live-spend control fix into this verification item.

## 11. Relationship to portfolio-level ROI

**Demonstrated ROI: none, and by design.** A cap never earns; it bounds loss.

**Plausible, and separated as such:** the caps bound the worst case of every other item in this
backlog. Their value is the difference between a mis-specified family costing one day's budget
and costing the account. That is not quantified here and must not be — the operator sets the
figures, and no plan may name or imply them.

**Evaluated by:** the §8 acceptance items. The portfolio-relevant statement this item produces
is binary: *"the two operator caps are proven to deny an order through the composition that
runs live, attributably, on a harness that can also admit one."* Today that sentence cannot be
said.

## 12. Assumptions, unresolved questions, blockers

**No blockers.** No ruling is required: the test asserts today's behaviour and changes no
semantics. **R-12** (the session order-count ceiling) is open but is explicitly out of scope.
Both round-1 reviewers independently confirmed no cap value is read or assigned.

**Assumptions to re-verify at execution time:**
- `pm_us_crh_v4` is still the live family. `PROGRESS.md:32` is stale on this point (it names
  `pm_us_crh_cont`); the audit's correction (`:119-120`) says the unit runs `pm_us_crh_v4`
  since `bcb82d6`. **Resolve from `deploy/systemd/breezy-trade-supervisor.service` and
  `deploy/families/`, not from `PROGRESS.md`.** If AUD-16 has landed, the file may be correct
  by then — check, do not assume.
- `tests/unit/operator_control_env.py` is still the sole whitelisted seam and still restores in
  a `finally`. If the assignment-scan's whitelist has changed, the injection route changes with
  it.
- The exit path's `allow_short=False` invariant and the exit-tag shape check are unchanged.
- The operator ruling recorded at `operator_controls.py:120-125` (per-position stays plain
  `LiveTradingPermissionError`) still holds. If it has been superseded, assertion 3's design
  simplifies to a class pin — check before building.

**Resolved this revision (was unresolved in round 1):** whether the permit-derived and
ledger-derived denials need separate fixtures. They do — a permit is minted with its ceilings
fixed, so cause 1 and causes 2/3 cannot both be driven from one permit fixture. §6 assertion 5
and §7 17b step 5 name the second fixture. This is a cost, not an open design question.

## 13. Review history

**Baseline self-score (2026-09-21, author): 92/100.** Named weaknesses: `safety.py:552-608`
ceiling derivation not verified; fixture wiring for two permit shapes left open.

### Round 1 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-17-r1-trading-bot-architect.md`) | 91/100 | None material; one MINOR (synthetic order left implicit). |
| silent-failure-hunter (`AUD-17-r1-silent-failure-hunter.md`) | 81/100 | **Two MATERIAL** — assertion 1 underspecified (vacuous-pass shape); no positive-control deliverable. |

**Dispositions — every defect, both reviewers:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — assertion 1 (per-position denial) never pins the specific cause, unlike assertion 2 which names `DailyBudgetExhausted`; an unrelated upstream veto would satisfy "denied + no POST" | **ACCEPTED, and verification of it exposed a further error in the plan itself.** Reading the artefact showed the per-position ceiling does **not** raise a nameable subclass: `operator_controls.py`'s `if cost > position_cap:` branch raises a **plain `LiveTradingPermissionError`**, deliberately, per the operator ruling recorded at `:120-125` ("raised ONLY by the daily-budget branch… the per-position ceiling and the clock-rewind branch stay plain `LiveTradingPermissionError`"). Round 1 had also **conflated** that ceiling with the permit-derived `SessionNotionalExhausted` gate, which is a different ceiling at a different call site. §2 is rewritten with a three-cause table and the correction called out. §6 replaces "assert denied" with three conjoined assertions — exact-type discrimination (`type(exc) is LiveTradingPermissionError`), reason-equality against a string built from the **imported** constant (never a literal, so layer B's file set is unchanged), and a **differential** (same order admitted when only that ceiling is raised), which excludes every upstream veto by construction. §7 17a step 2 makes the layer-B tolerance an empirical pre-check with a stated fallback. Causes 1 and 2 are pinned by class, each with its own named assertion and `_mark_budget_exhausted` latch check. |
| 2 | hunter | **MATERIAL** — no positive-control ("would otherwise be admitted") case scoped as a deliverable; §9 states the requirement but §7/§8 do not carry it; all four assertions could pass vacuously | **ACCEPTED in full.** The ADMIT case is now §6 assertion 2, **§7 17b step 1 — scoped first, before any denial test** — and §8 item 3, which states explicitly that a denial transcript submitted without a green ADMIT is not acceptance. The composition-level boundary cases (exactly-at-ceiling admitted, exactly-at-budget admitted, a refusal costs no budget) are promoted from §9 prose into §7 17b step 7 and counted in §8. The assertion count moved from four to ten named tests. |
| 3 | hunter | **MATERIAL (structural)** — §9-vs-§7/§8 inconsistency left unresolved | **ACCEPTED.** §9 now carries a case→step→acceptance mapping table, so every validation requirement is traceable to an ordered step and an acceptance item. Nothing is asserted in §9 that is not scoped elsewhere. |
| 4 | architect | **MINOR** — state explicitly that the driven order is synthetic/hand-built, not strategy-generated | **ACCEPTED, with the reasoning made explicit rather than asserted.** §6 states it in full: the order objects are hand-built (the shape `tests/unit/test_polymarket_us_exec_client.py` already uses), because the caps enforce at the **exec-client boundary** downstream of sizing, and making the v4 strategy actually decide to submit would put the test behind R-11/MP-B (§5's sizing exclusion) and would measure the strategy rather than the cap. What must be real — shipped manifest, composition dispatch, exec-client factory, ledger, permit, gate ordering — is enumerated separately so the bound cannot be read as a shortcut. |
| 5 | (author, round 1 §13) | Fixture wiring for two permit shapes left open | **ACCEPTED (self-raised, now closed).** §12 records it as resolved: a permit's ceilings are fixed at mint, so causes 1 and 2/3 genuinely require two fixtures. §6 assertion 5 and §7 17b step 5 name it as a cost, not an open question. |

**Rejections:** none. Every defect from both records was verified against source before
disposition, and verifying defect 1 produced a correction to the plan's own enforcement map —
the round-1 §2 description of enforcement point 1 was wrong and is now fixed.

**Note for round 2 on the architect record:** it withheld 9 points (19/19/12/18/13/10) while
finding one MINOR, now closed by disposition 4. The specificity deduction (12/15) was tied
explicitly to that MINOR and should be recoverable. The acceptance (18/20) and autonomy (13/15)
deductions named no change; this revision nonetheless strengthened both (ten scoped tests, the
gating ADMIT rule, the no-POST assertion, and an explicit statement that the
`_mark_budget_exhausted` latch must not be cleared or tested around). Round 2 should award or
name the change.

**Revision 2 self-score (honest, post-revision):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Closes G-16 as stated and adds the third denial cause the gap did not know about. Still bounded to the exec-client boundary — correct, and now argued rather than assumed. |
| Technical correctness and evidence grounding | 20 | 19 | All three causes, their exception types, their catch sites, the latch behaviour, the exit-side branch and the operator ruling comment re-read from source this session; round 1's conflation corrected. `safety.py:552-608`'s ceiling derivation is still cited, not re-verified line by line. |
| Implementation specificity and feasibility | 15 | 14 | Ten named tests in dependency order, an attribution strategy that survives the layer-B constraint, an empirical pre-check with a stated fallback, the synthetic-order bound, and the two-permit-fixture cost. Exact fixture construction remains the implementer's. |
| Acceptance criteria and validation quality | 20 | 19 | Eight items; the ADMIT case gates acceptance of every denial; the differential is required in the transcript; three `git diff`-empty guards plus the layer-B file-set check make "weaken a safety test" mechanically detectable. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Directly about the unattended-spend bound; neither-control-set, boundary-admit, no-cost-on-refusal and the latch-must-not-be-cleared rule are all pinned. Adds no new runtime control, correctly. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No invented or implied cap magnitude; R-12 and MP-B/R-11 routed to their owners; test-only, so rollback risk is nil. |
| **Total** | **100** | **95** | |

### Round 2 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`AUD-17-r2-silent-failure-hunter.md`) | **95/100** | None MATERIAL — both round-1 MATERIAL defects verified genuinely fixed against source. 1 MINOR. |
| trading-bot-architect (`AUD-17-r2-trading-bot-architect.md`) | **100/100** | None. Re-derived the three-cause table, every exception type and catch site independently; noted only ±1-2 line citation drift, explicitly not rated a defect. |

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MINOR** — §7 17a step 2 hedges the reason-equality sub-assertion but never states what happens to the **test's own pass/fail shape** if the fallback triggers | **ACCEPTED IN FULL, and stated in both places rather than one.** §7 17a step 2 now says plainly: on fallback the per-position denial test **still PASSES** on exact-type discrimination (`type(exc) is LiveTradingPermissionError`) plus the differential alone — not skipped, not xfailed, §8 acceptance status unchanged. Two bindings were added beyond the ask, because a bare "it still passes" invites the wrong repair: (a) the fallback and the scan output that forced it must be **recorded in the transcript**, so a reader knows the test runs two-assertion rather than three; (b) dropping assertion 2 is the **only** permitted response — amending the assignment scan to accommodate a test is forbidden by §5, and a test that cannot be written without touching the scan is a wrong test. §9 carries the matching argument for *why* it costs nothing: assertion 2 is the weakest of the three and corroborates what the differential already establishes structurally; neither of the two named vacuity guards (ADMIT case, differential) is contingent on layer B. |
| 2 | architect | ±1-2 line citation drift, explicitly "not a defect, no claim's substance depends on the exact line" | **NOTED, no change.** The reviewer independently re-derived `submit_veto`, `assert_live_order_submission_permitted`, the exit-side branch and both catch sites from source and confirmed the ordering; re-anchoring to ±1 line would churn §6 and §9 without changing a claim. Recorded rather than silently absorbed. |
| 3 | both | Round-1 MATERIAL fixes (per-position attribution via three conjoined assertions; the ADMIT positive control gating acceptance) verified genuinely fixed against source | **NOTED**, no change required. Both reviewers independently confirmed the per-position ceiling raises a plain `LiveTradingPermissionError` (`operator_controls.py:118-126`) and that `type() is` excludes the two subclasses. |
| 4 | architect | `test_operator_reserved_controls.py:708` pins the **set of importing files**, not the ledger-construction mechanism; its name is stale relative to its own docstring | **NOTED and left as scoped** — the reviewer's own verdict is that §7 17a step 3 correctly flags it for the implementer to resolve and report either way rather than assuming a reading. The finding is recorded here so the executing session inherits it: the test's actual assertion is an exact 6-file import list. |

**Rejections:** none.

**Revision 3 self-score (conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-16 closed as stated, with the third denial cause the gap did not know about folded in. Still a *verification* item: it proves the caps bind, it does not add a control. |
| Technical correctness and evidence grounding | 20 | 19 | Every exception type, catch site, latch and the gate ordering were independently re-derived from source by both reviewers and match. Deducted 1 for the acknowledged ±1-2 line citation drift, left uncorrected by choice. |
| Implementation specificity and feasibility | 15 | 14 | Ten named tests in dependency order; the layer-B fallback now has a stated pass/fail consequence and a forbidden repair. Deducted 1: the two-permit fixture and the synthetic-order construction remain the costliest unspecified mechanics. |
| Acceptance criteria and validation quality | 20 | 19 | Eight items; ADMIT gates every denial; the differential is a required transcript element; three `git diff`-empty guards plus the layer-B file-set check. The fallback now also has a transcript obligation. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared are all pinned; the no-POST assertion runs under the no-egress sandbox. Adds no new runtime control, correctly — so it detects a broken cap at test time, never at run time. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No cap value or magnitude read, assigned or implied; R-12 and MP-B/R-11 routed to their owners; test-only, so rollback risk is nil. |
| **Total** | **100** | **95** | |

### Round 3 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-17-r3-trading-bot-architect.md`) | **100/100** | **None found.** Re-derived the three-cause exception split from `operator_controls.py` directly (plain `LiveTradingPermissionError` at `:384-387`, `DailyBudgetExhausted` subclass at `:126`, ruling text at `:120`) without reading prior rounds' quotations first. |
| silent-failure-hunter (`AUD-17-r3-silent-failure-hunter.md`) | **95/100** | **None MATERIAL.** 1 MINOR — the layer-B fallback, once taken, is durable by default: nothing re-triggers a review of assertion 2 if layer B's tolerance is later relaxed. |

**Readiness is the LOWER, 95.** The architect's 100 explicitly states that no point was withheld
without a nameable defect and required change; it is nonetheless **not treated as evidence of
correctness** — the same reviewer's 100 on AUD-14 in round 2 sat beside a MATERIAL defect, and the
hunter did find a real (if minor) residual here on the same artefact. The 95 is the reading this
revision acts on.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MINOR** — the fallback's recording obligation is a one-time transcript artefact, not an ongoing check; if layer B's tolerance relaxes, nothing restores assertion 2 | **ACCEPTED and specified, not noted.** The reviewer offered a §9 note as sufficient; a note is exactly the "durable by default" shape the defect describes, so a **mechanism** was written instead. §7 17a gains **step 2a**: on the fallback path only, a precondition pin `test_layer_b_still_refuses_the_imported_constant_style_so_assertion_2_stays_dropped`, which asserts the *premise* through the scan module's own already-public helpers — `files_naming_a_control()` (`tests/unit/test_operator_control_assignment_scan.py:347`, the same helper the existing census test at `:610` calls) plus `_mentions_control`/`_control_aliases` (`:157`, `:171`), each verified present at HEAD this revision — and **fails loudly** when layer B starts tolerating the imported-constant form, with an assertion message naming the restoration action. It **calls** the scan and never amends, copies or re-implements it, so §5's ban is untouched and the assignment-scan test set stays byte-identical (§8 item 5 unchanged). §8 item **2a** makes the pin acceptance *and requires it to be demonstrated capable of failing*, so the revisit mechanism cannot itself be vacuous. §9 records why `@pytest.mark.xfail(strict=True)` was **rejected**: layer B's refusal does not manifest as a failure of this test — it manifests in the scan's own census — so an xfail-strict would XPASS under both tolerances and fire on the wrong signal. |
| 2 | hunter | Confirmed "still passes, unskipped" cannot hide a lost assertion: assertion 3 (the differential) excludes every upstream veto by construction and no counter-example could be built | **NOTED**, no change required; §9's argument is unchanged and now carries the revisit mechanism beside it rather than in place of it. |
| 3 | architect | No defect; 100/100 on a from-scratch re-derivation of the exception hierarchy | **NOT AWARDED as evidence of correctness** (the standing rule), but the re-derivation itself is accepted as independent confirmation of §2's three-cause table, which this revision does not touch. |
| 4 | both | ADMIT-gating, the differential, the exit-side negative and the no-value-anywhere scan all re-confirmed | **NOTED**, no change required. |

**Rejections:** none.

**Revision 4 self-score (conservative — the item is verification-only and test-only, but its one
residual was a *durability* gap, which is the class this backlog has repeatedly under-weighted):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-16 closed as stated, with the third denial cause folded in. Still a *verification* item: it proves the caps bind, it does not add a control. |
| Technical correctness and evidence grounding | 20 | 19 | The exception hierarchy was independently re-derived from source by both reviewers and matches; the four scan helpers the new pin calls (`:157`, `:171`, `:347`, `:610`) were confirmed present at HEAD this revision. Deducted 1 for the acknowledged ±1-2 line citation drift, left uncorrected by choice. |
| Implementation specificity and feasibility | 15 | 14 | Ten named tests plus the conditional pin, each in dependency order; the fallback has a stated pass/fail consequence, a forbidden repair, and now a named restoration trigger. Deducted 1: the two-permit fixture and the synthetic-order construction remain the costliest unspecified mechanics. |
| Acceptance criteria and validation quality | 20 | 19 | Nine items now; ADMIT gates every denial; the differential is required in the transcript; the pin must be shown capable of failing; three `git diff`-empty guards plus the layer-B file-set check. Deducted 1: the pin is conditional, so on the no-fallback path the acceptance is a recorded answer rather than an artefact. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared are pinned; the no-POST assertion runs under the no-egress sandbox. Adds no new runtime control, correctly — so it detects a broken cap at test time, never at run time. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No cap value or magnitude read, assigned or implied; R-12 and MP-B/R-11 routed to their owners; test-only, so rollback risk is nil. |
| **Total** | **100** | **95** | |

### Round 4 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-17-r4-trading-bot-architect.md`) | **97/100** | **None found**, MATERIAL or MINOR. Confirmed the four scan helpers present at `:157`, `:171`, `:347`, `:610` and judged the pin "sound — it fails exactly when layer B's tolerance changes". |
| silent-failure-hunter (`AUD-17-r4-silent-failure-hunter.md`) | **88/100** | **1 MATERIAL** — the precondition pin targets layer B, which can **never** exhibit the failure it claims to guard; §8 item 2a's "demonstrated capable of firing" therefore has no legitimate mechanism. |

**Readiness is the LOWER, 88** — a 9-point spread on the same artefact, and the spread is again
the finding. **The architect's 97 named no defect and required no change**, and its coherence
check endorsed the pin in the exact terms the hunter falsified: *"it fails exactly when layer B's
tolerance changes (the premise)"*. Both reviewers verified the **same four helper line numbers**;
only one read what `files_naming_a_control` actually **does** with them. Per this backlog's
standing rule the 97 is not evidence of correctness — and this is the third item in this cluster
where a no-defect architect score sat on top of a MATERIAL defect the other reviewer found. Its
substantive confirmations (the three-cause exception table at `operator_controls.py:120`, `:126`,
`:386`; the ADMIT-gates-every-denial ordering; the synthetic-order bound) are accepted; its
verdict on the pin is not.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — the §7 17a step 2a pin targets layer B, a **byte census** over the env-var NAME strings; the identifier `MAX_POSITION_COST_USD_ENV_VAR` does not contain `BREEZY_MAX_POSITION_COST_USD` as a substring, so layer B can never flag the imported-constant style, was never intolerant of it, and cannot drift — making the pin's premise permanently true and the pin unable to fail | **ACCEPTED IN FULL. The defect is real, it is reproduced from source, and the pin is RETARGETED rather than re-worded.** Verified this revision by reading the module: `files_naming_a_control()` (`tests/unit/test_operator_control_assignment_scan.py``:347-358`) builds `needles` from `CONTROL_ENV_VAR_NAMES` (`:90-92` = `frozenset(operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS)`) and tests `needle in blob` — a literal byte census, never touching `CONTROL_CONSTANT_IDENTIFIERS` (`:99-104`). The reviewer is right on every step, including the consequence: the only way to make layer B flag the identifier form is to edit the scan, which §5 forbids. **The drift-capable mechanism is layer A, exactly as the reviewer's option 1 proposed, and the question they asked about its scope is now answered from source rather than left open:** `_mentions_control` (`:157-167`) walks with `ast.walk` and returns True on any nested `ast.Name` in `CONTROL_CONSTANT_IDENTIFIERS` — including inside an f-string — and rule **A6** (`:285-295`) fires when such a node appears in the arguments of **any** call whose callee is outside `PERMITTED_CONTROL_ARGUMENT_CALLEES` (`:126-136`) or `_READER_CHAIN_CALLEES` (`:138`); a new file under `tests/unit/` is inside `SCAN_ROOTS` (`:86`) and outside layer A's exempt set (`:321`). So layer A both **constrains** the assertion's shape today and **can** widen or narrow under ordinary maintenance of the scan for unrelated reasons — which is precisely the drift a pin should catch. §6's assertion 2, §7 step 2, §7 step 2a, §8 item 2a and §9 are all corrected to name layer A; the withdrawn layer-B framing is named as withdrawn in each place rather than quietly replaced. |
| 2 | hunter | **MATERIAL (same defect, second half)** — no specified, legitimate way to satisfy "demonstrated capable of firing": editing the scan breaches §5 *during execution* even if reverted, and the monkeypatch alternative is nowhere named in the plan | **ACCEPTED IN FULL, and answered with a mechanism that needs neither.** The retargeted pin calls `find_control_assignments(path, source)` (`:224`), which is public and takes a **source string**, so both directions are exercised against **synthetic sources**: branch (a) — the bare-comparison shape — must return `[]`; branch (b) — the same identifier handed to an unapproved callee — must return a non-empty list carrying rule `A6`. **Branch (b) IS the firing**, produced in the same run, so the "capable of failing" demonstration is intrinsic rather than staged: no monkeypatch of `files_naming_a_control`, no temporary edit, nothing to revert, and §8 item 5's empty `git diff` on `tests/unit/test_operator_control_assignment_scan.py` holds in the same transcript. This is the repo's **own** established idiom, not an invention: `test_the_scan_fires_on_every_planted_assignment_form` (`:452-455`) and `test_the_scan_does_not_fire_on_asserting_about_a_control_name` (`:470-479`) both feed planted source strings to the same helper for exactly this purpose — and the latter additionally pins that the bare-comparison form §6 now mandates is already tolerated, which is what makes branch (a) a real assertion rather than a hope. §8 item 2a is rewritten to require the two-branch output as the acceptance artefact. |
| 3 | coordinator-required consequence | If layer B was never the constraint, is the §7 step 2 **fallback** itself mis-specified? | **YES, and corrected — scope kept, framing fixed.** §7 step 2 no longer asks for "layer B's tolerance"; it requires **both** layers run against a scratch draft with both outputs pasted: layer B green **by construction** (recorded because §8 item 7 requires it, not because it is in doubt) and layer A green **only if** the non-call shape is used. A three-rung response ladder replaces the single "drop it" branch: **(a)** rewrite the assertion into the clean non-call shape §6 specifies — the first and expected repair, since a test that trips the scan is a wrong test; **(b)** only if no in-scope shape is clean, drop reason-equality and let the differential carry attribution; **(c)** never the scan, under every branch. Nothing is softened: assertion 2 is now **more** likely to survive, and the two structural guards (ADMIT case, differential) are untouched. |
| 4 | coordinator-required consequence | The pin was created **only** on the fallback path | **CHANGED to unconditional**, because the corrected target bears on both paths: branch (a) is the premise that keeps assertion 2 legal when it is **kept**, branch (b) the premise that justified dropping it when it is **dropped**. Conditioning it on the fallback would leave the now-expected path — assertion 2 retained — unguarded, which is the durable-by-default shape round 3 raised in the first place. §8 item 2a is unconditional to match, and additionally records which rung of the ladder was taken. |
| 5 | architect | No defect; endorsed the pin as "fails exactly when layer B's tolerance changes"; independently re-derived the three-cause table and confirmed the ADMIT-gates-denial ordering and the synthetic-order bound | **Confirmations NOTED and accepted; the endorsement NOT AWARDED** — it is the specific claim disposition 1 falsifies from the same file the record cites. Recorded as a miss of the same shape as rounds 2 and 3 on this backlog: the helper **locations** were verified, the helper's **behaviour** was not. |

**Rejections:** none. The MATERIAL defect was reproduced from `tests/unit/test_operator_control_assignment_scan.py`
before any edit, and the retarget is built on lines read this revision, not on the reviewer's
summary of them.

**Revision 5 self-score (conservative — the round-4 defect is the worst kind this backlog
records: a mechanism ADDED in round 4 to close a vacuity risk was itself vacuous, and it was
self-scored 19/20 on acceptance and endorsed by a reviewer before anyone read what the helper
did; no criterion is scored as if that had not happened):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-16 closed as stated, the third denial cause folded in, scope still correctly verification-only. Unaffected by the pin defect. Deducted 1: the item proves the caps hold at test time only — named, not hidden. |
| Technical correctness and evidence grounding | 20 | **16** | The layer-A/layer-B split is now derived from the module's own code (`:86`, `:90-92`, `:99-104`, `:157-167`, `:224`, `:285-295`, `:321`, `:347-358`, `:452-455`, `:470-479`), all read this revision. Deducted 4: the previous revision asserted a property of `files_naming_a_control()` that its four-line body contradicts, and cited the helper's line number as if that were verification — a citation-vs-behaviour failure, which this plan is not the first item in this cluster to make. |
| Implementation specificity and feasibility | 15 | **13** | The pin is now literal: the helper called, its two synthetic sources, the expected verdict and rule name for each, the failure message per branch, and the self-non-tripping argument for the pin's own source. Deducted 2: the two-permit fixture and the synthetic-order construction remain the costliest unspecified mechanics, unchanged. |
| Acceptance criteria and validation quality | 20 | **17** | Item 2a now demands the two-branch transcript as the firing demonstration, unconditional, with §8 item 5's empty `git diff` required in the same run, plus the recorded ladder rung. Deducted 3 rather than 1: the acceptance item that was supposed to prevent a vacuous pin **passed a vacuous pin**, so this criterion is scored on that record, not on the fix alone. |
| Autonomous operation, failure handling and recovery | 15 | 14 | Unchanged and not implicated: neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared stay pinned, and the no-POST assertion runs under the no-egress sandbox. Deducted 1: a test-only item detects a broken cap at test time, never at run time — correct for the scope, and the ceiling that scope can reach. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: no cap value or magnitude read, assigned or implied; R-12 and MP-B/R-11 routed to their owners; test-only, so rollback risk is nil. |
| **Total** | **100** | **89** | |

**Latest score:** 89 (revision 5 self-score). Round-4 peer scores **97** (architect, no defect
named) and **88** (hunter); **readiness is the lower, 88**. Round-3 peer scores 100 and 95;
round-2, 95 and 100.
**Readiness: NOT READY — round 5 delta review pending.**
**Blockers: none.** R-12 remains open and remains explicitly out of scope; this item creates no
new ruling need and touches no operator-reserved value.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `df21c342c630afa55a9b5fafdcd5aa5f9b48a5e0d33b56b8cf13bd7957bd4e9c`
- **Baseline self-score:** 92/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `silent-failure-hunter` round 5: 100/100 — `reviews/AUD-17-r5-silent-failure-hunter.md`
  - `trading-bot-architect` round 5: 100/100 — `reviews/AUD-17-r5-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None. R-12 stays open and out of scope.
- **Full review history:** 10 records, `reviews/AUD-17-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
