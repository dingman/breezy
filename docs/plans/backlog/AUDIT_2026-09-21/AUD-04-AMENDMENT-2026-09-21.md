# AUD-04 safety-pin disposition — peer-reviewed record (2026-09-21)

Design: code-architect. Adversarial review: security-reviewer, ENDORSE-WITH-CHANGES — all three rows
verified justified against source; required change applied: a permanent AST test pins that
`scripts/analysis/portfolio_roi_report.py` imports exactly the cent-rounding helper from the
operator-cap module, so the file-level pin rows cannot become a blanket admission.

Also recorded here: the plan has no "capture half" (the balance series is parsed from the node's
once-per-boot `AccountState(` log line; a balance poll is explicitly excluded), so the WHOLE plan was
implemented. Conventions the plan predates were applied: `OnFailure=breezy-study-failed@%n.service`,
`EnvironmentFile=-%h/.config/breezy/alerts.env` as the only env file, `log_alert_egress_status`
before sink resolution. Review-driven hardening beyond the plan: BUY/SELL handling (the plan assumed
the live family never sells), BALANCE_UNKNOWN / NO_PRIOR_BALANCE rows, a non-bypassable runtime
ledger-partition assertion, atomic report writes, per-family store pooling.

---

# AUD-04 — PIN DISPOSITION (P-A / P-B / P-C) — 2026-09-21

Scope: the uncommitted `scripts/analysis/portfolio_roi_report.py` + `tests/unit/test_portfolio_roi_report.py`. Design only; no repo file edited by this author.

## P-A — `test_operator_reserved_controls.py::test_the_mechanism_has_no_production_call_site_yet`
**Detector (:739-754):** SUBSTRING scan — every `*.py` under `src/`+`scripts/` whose TEXT contains `operator_controls`, excluding `operator_controls.py`, `==` a sorted 6-row list. Not an import scan: a bare comment citation trips it.
**Protected property:** *no module under `src/`/`scripts/` may come to reference the operator-cap module without a reviewer consciously declaring it* — the docstring's own words, "a THIRD importer arriving here undeclared is still the accidental-wiring signal this test exists to catch." A review tripwire on the cap module's reference surface, not a ban: two of the six rows exist precisely for pure-helper users (`exec/client.py`, `current_rung_hold/continuous_strategy.py`, importing only `utc_day_for_ns`, "reads no control value").
**Violates / satisfies / outside?** The report FALLS INSIDE the detector (imports `_round_cost_up_to_cent` at :69; cites the module in comments at :238, :482) and SATISFIES the property once declared: no cap read, no env read, no accessor call (`operator_max_*` absent), no `DailySpendLedger`, no assignment, offline `Type=oneshot` outside the node. Same class as the two `utc_day_for_ns` rows.

## P-B — `test_polymarket_us_readonly_guard.py::test_c10_...reference_pins` (`operator_controls` half)
**Detector (`_modules_importing`, :2182-2199):** AST `Import`/`ImportFrom` over `EGRESS_SCAN_ROOTS = ("src","scripts")`, `==` a 6-row set. **Same protected property, stricter instrument:** the exact set of modules that IMPORT the cap module is pinned, so a new caller of the cap machinery cannot appear unreviewed. Same answer: inside, satisfies, declare it.

## DECISION P-A + P-B — (1) WIDEN each by one row. (2) and (3) rejected.
L-12 (`LESSONS.md:620`, "Widen an exact-set barrier, never relax it") is the house move; both comparisons stay `==`. The new member is property-preserving: a read-only offline consumer of a pure quantiser — the exact `utc_day_for_ns` precedent. Declaring it is what the pin is FOR.

**Rejected (2) — extract the helper to a public module neither pin scans** (e.g. `breezy/domain/money.py`; legal under the layers contract, `pyproject.toml:75-87`, `adapters` above `domain`):
- Edits `operator_controls.py`. AUD-04 §5 excludes "No change to any existing `src/` module" (sole sanctioned addition: `runtime/alert_ladder.py`). That file is the repo's most safety-sensitive module, under the layer A-D assignment scan (`DEFINITION_MODULE`, `test_operator_control_assignment_scan.py:111`). Editing it to serve a report inverts the risk ordering.
- **No such module exists and convention is the opposite:** five sites already carry a local `_CENT`/`quantize` (`operator_controls.py:150`, `current_rung_hold/decision.py:315`, `fees.py:475`, `exec/reports.py:976,994`, `exec/submit_chain.py:783`). A money module those five would not adopt is a sixth definition, not a single source of truth (YAGNI).
- **Defeats the pin rather than satisfying it:** the coupling remains; only the tripwire's visibility of it is removed. "Fewest modules reference the cap module" is a means to reviewer visibility, never an end that outranks it.
- **P-A is a substring scan**, so avoidance also requires scrubbing the explanatory citations at :238/:482 — trading traceability for a green scan.
- Blast radius: `operator_max_*`/`order_cost_usd` have 7-8 callers; moving their shared quantiser touches the authorisation and true-up path for a reporting need. (Checked: nothing pins `operator_controls.py`'s exact CONTENTS — the assignment scan derives `CONTROL_CONSTANT_IDENTIFIERS` by reflection over `str`-valued attributes (:99-106), so a moved FUNCTION breaks no pin. The objection is risk and scope, not a second pin.)

**Rejected (3) — restate the quantiser locally** (as the script does for `_SEVEN_DAYS_NS` :470-474 and `utc_day_for_ns` :479-484): contradicts D4's mandate that capital-deployed reuse the shipped cost definition so report and live cap arithmetic "can never disagree"; the per-day tolerance at :615-621 is derived from the rule being exactly ROUND_UP-to-the-cent, so a drifting copy falsifies the tolerance. Still trips P-A unless the citations are scrubbed.

**Residual (non-blocking):** the import is a PRIVATE name across a package boundary, and the same file declines to import `trial_scorer._SEVEN_DAYS_NS` for that reason. Worth one sentence in the script docstring: the public sibling `order_cost_usd` is the wrong shape (it quantises `price x quantity`, not `cost + fee`), so no public entry point to the quantiser alone exists, and D4's single-definition mandate outranks the private-name convention. No lint forbids it (`SLF` unselected; `pyproject.toml` extend-selects `E501` only).

### Exact edits
**`tests/unit/test_operator_reserved_controls.py`** — append to the docstring after the "Sixth, declared 2026-09-14" paragraph:
```
    Seventh, declared 2026-09-21 (AUD-04, portfolio ROI report): the OFFLINE,
    read-only `scripts/analysis/portfolio_roi_report.py` imports ONE pure
    symbol, `_round_cost_up_to_cent`, to quantise `cost + fee` per ledger fill
    into capital-deployed, so the report cannot round differently from the live
    cap arithmetic and the ledger true-up (AUD-04 §6 D4). It imports no money
    accessor, reads no operator value, constructs no ledger, and runs in a
    `Type=oneshot` outside the node -- the same pure-helper class as the exec
    client's and the strategy's `utc_day_for_ns` rows above. This scan is a
    SUBSTRING scan, so the module is also matched by that script's explanatory
    docstring citations; those are documentation, not calls.
```
and insert as the FIRST element of the sorted list at :747 (sorts before `scripts/operator/...`):
```
        "scripts/analysis/portfolio_roi_report.py",
```
**`tests/unit/test_polymarket_us_readonly_guard.py`** — append to the docstring after the "WIDENED again (AUD-02b, 2026-09-21)" paragraph:
```
    WIDENED again (AUD-04, 2026-09-21): old -> new adds the offline portfolio
    ROI report, an analysis script importing ONLY the pure cent quantiser.
    Same property, no accessor, no operator value -- see the row's own comment.
```
and add to the `_modules_importing("operator_controls")` set (:2295-2324):
```
        # WIDENED (AUD-04, 2026-09-21), not relaxed (L-6/L-12): the comparison
        # is still `==`; old -> new added exactly this one path. The offline
        # portfolio ROI report imports ONE pure symbol,
        # `_round_cost_up_to_cent`, so `capital_deployed` quantises `cost+fee`
        # with the SAME ROUND_UP-to-the-cent rule `order_cost_usd` and
        # `DailySpendLedger.true_up_booking` share (§6 D4). It imports no money
        # accessor (`operator_max_position_cost_usd`/`operator_max_daily_
        # budget_usd`), reads no operator value, opens no ledger, and runs
        # offline in a `Type=oneshot` -- the same pure-helper class as the
        # `utc_day_for_ns` rows above.
        "scripts/analysis/portfolio_roi_report.py",
```

## P-C — `test_execution_egress_firewall_guard.py::test_x1_the_live_scan_actually_reaches_a_test_that_imports_the_exec_package`
**Protected property:** *every TEST module importing the `exec/` package is enumerated, so a new exec-importing suite cannot land without a reviewer confirming it carries none of `SOCKET_RESTORING_MARKERS` and opens no socket* (markers :240 = `{"allow_socket","live","venue_live","real_money"}`; detector `exec_importing_test_modules` :3054-3060 over `TEST_SCAN_ROOTS = ("tests",)`; set at :3345+).
**Verified:** the new module imports `DurableFillRecord` from `exec.client` at :33 and nothing else from `exec/`. A scan for `allow_socket`, `live`, `venue_live`, `real_money`, `pytest.mark`, `socket`, `PolymarketUSExecutionClient`, `httpx`, `requests` returns ZERO hits — no pytest mark at all, no client, no socket; `DurableFillRecord` built from literal fields at :460-461. Exactly the pinned `test_fill_time_count.py` / `test_live_family_tally_fill_source_cli.py` idiom. **DECISION: widen by one row; the test module needs no change.**
Append to the comment block above `assert exec_importing_test_modules() == {`:
```
    #
    # Old -> new (this row, AUD-04 2026-09-21, portfolio ROI report): added
    # `tests/unit/test_portfolio_roi_report.py`, which imports
    # `DurableFillRecord` from `exec.client` to build ledger-fill fixtures for
    # the offline capital-deployed / cash-identity report -- the SAME
    # plain-data-record idiom as its `test_fill_time_count.py` and
    # `test_live_family_tally_fill_source_cli.py` siblings above, so fixtures
    # are encoded by the shipped record, never a second hand-written blob.
    # WIDENED, not relaxed (L-6/L-12): the comparison is still `==`; the module
    # carries NO pytest mark at all -- none of `SOCKET_RESTORING_MARKERS`
    # appears in it -- constructs no client and opens no socket.
```
and the row, alphabetically adjacent to the other `test_p*` entries:
```
        "tests/unit/test_portfolio_roi_report.py",
```

## Sweep — other pins the AUD-04 files can trip (reported, not actioned)
1. `test_study_failure_alert.py::test_every_study_unit_declares_an_onfailure_handler` — TREE-scanning (:60-70), so `deploy/systemd/breezy-portfolio-roi.service` is auto-in-scope once its `.timer` sibling exists: must carry `OnFailure=breezy-study-failed@%n.service`; only permitted `EnvironmentFile` is `%h/.config/breezy/alerts.env` (`breezy-trade.env`/`polymarket.env`/`operator.env` refused). Unit-file requirement, no pin row.
2. `test_analysis_units_serialized.py` — `_HEAVY_TIMERS`/`_HEAVY_SERVICES`/`_WRAPPERS` are exact frozensets (:366-380), re-asserted inline at :561/:615/:741. If the new timer/service/wrapper classify heavy they need rows plus `Slice=breezy-studies.slice` and a tick outside the LST-derived protected window. This file and `test_analysis_units_memory_capped.py` (`_CANDIDATE_UNITS`/`_EXISTING_UNITS`, :29/:56) are ALREADY modified in the tree by a sibling agent — check before duplicating.
3. `test_deploy_timer_hours.py` — tick-uniqueness scan (:135-181); the plan's `17:40:00Z` must stay unowned by `breezy-family-tally@.timer` / `breezy-score-live-trials.timer`.
4. `[tool.mypy].files` includes `scripts/analysis` (`pyproject.toml:177`) — the 1739-line script runs under `strict = true`. A gate, not a widening.
5. F1 fee guard (`test_polymarket_us_fee_guard.py`, `FEE_SCAN_ROOTS = ("src","scripts")`) — fires only on `is_venue_touching` modules. The report reads `fill.cumulative_fee`, so if a later disposition changes which adapter modules it imports, the classification can flip and F1 would demand an `assert_fee_schedule_known` guard. Does not fire today (the gate reported only P-A/B/C).
6. `test_polymarket_us_fee_schedule_pin.py::study_theta_sites_from_analysis_scripts` (:212-220) — scans `scripts/analysis/*.py` for theta-named literal `Decimal` bindings; the report declares none. Clear.
7. `test_operator_control_assignment_scan.py` (layers A-D over `src`/`scripts`/`tests`) — the report assigns nothing and names neither reserved identifier; adds no violation. Its current RED is the known, unrelated AUD-17 planning-doc failure.
8. `test_alert_egress.py`/`test_runtime_health.py` — no exact inventory of `health` importers exists; `runtime/health.py` is an explicit non-venue-touching exemption (`readonly_guard:982-989`, `probe_containment:290-293`). The `health`/`alert_ladder` imports add no pin row.

## Final touch-set
1. `tests/unit/test_operator_reserved_controls.py` — 1 docstring paragraph + 1 list row.
2. `tests/unit/test_polymarket_us_readonly_guard.py` — 1 docstring paragraph + 1 commented set row.
3. `tests/unit/test_execution_egress_firewall_guard.py` — 1 comment paragraph + 1 set row.
No `src/`, no `scripts/`, no `operator_controls.py`, no deploy unit, no `pyproject.toml`. The two AUD-04 files are unchanged (the optional script-docstring sentence under "Residual" is a nicety, not required for green).

## Acceptance criteria (mechanically checkable)
- **AC1** All three asserts still use `==`; `git diff` on the three test files shows net +1 collection element each and zero deletions from any pinned set (no `in`, no subset test, no allowlist, no `skip`/`xfail`).
- **AC2** The three named tests pass in one focused invocation.
- **AC3** Non-vacuity: deleting the new row from each set turns that test RED; restore after.
- **AC4** `grep -c -E 'allow_socket|venue_live|real_money|pytest\.mark|socket|PolymarketUSExecutionClient' tests/unit/test_portfolio_roi_report.py` == 0.
- **AC5** `grep -n 'operator_max_daily_budget_usd\|operator_max_position_cost_usd\|os.environ\|getenv' scripts/analysis/portfolio_roi_report.py` shows no cap accessor and no read of either reserved name.
- **AC6** `_modules_importing("operator_controls")` and the P-A list each hold exactly 7 elements; `exec_importing_test_modules()` holds exactly one more than before.
- **AC7** Full gate via `scripts/ci/run_tests_no_egress.sh` (read the EXIT CODE): P-A/P-B/P-C green, the only remaining RED being the pre-declared AUD-17 planning-doc failure.
- **AC8** `lint-imports` passes (this disposition introduces no new `src/` import edge).
