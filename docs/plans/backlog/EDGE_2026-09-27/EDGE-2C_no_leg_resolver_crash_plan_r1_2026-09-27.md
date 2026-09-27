# EDGE-2C — NO-leg resolver crash: `instrument_id_to_slug` raises outside any `try` and kills the AMBIGUOUS resolver (plan r1, 2026-09-27)

Severity: HIGH (latent L-48 deadlock, armed by the first NO-side with-id AMBIGUOUS). Status: PLAN r1, split out of EDGE-2 r1 slice C at the coordinator's request.
Standalone and minimal. **Depends on nothing** — not on EDGE-2 Step 0, not on any other EDGE-2 slice, not on any other EDGE item.
**HARD precondition of any re-arm.** No re-arm of any family that can place a NO-leg order (today: `pm_us_crh_v4`, NO-side hunting is a requirement) may happen before this is merged, deployed on a node respawn, and proven live per §9. EDGE-5 and any A1-class re-arm ruling must list EDGE-2C as a gate row.

---

## 1. Goal and acceptance criteria

Goal state: a with-id AMBIGUOUS intent on the NO leg is resolved by the resolver exactly as a YES one is, and no exception raised while deriving a slug or a holding can ever end the periodic resolver coroutine.

1. **AC1 (no raise).** For a `^no` instrument, the resolver's post-GET branch derives the venue slug with `base_slug_of` (`symbology.py:298`, already imported at `exec/client.py:324`). `instrument_id_to_slug` is no longer called in `_resolve_ambiguous_intents`.
2. **AC2 (leg-aware holding).** The holding corroboration takes the order's leg (`leg_of(instrument.id)`). It uses the ruled leg semantics of `reports._position_leg` (`exec/reports.py:1426-1469`): a YES holding is `netPosition > 0`, a NO holding is `netPosition < 0` on the base slug (venue nets a NO holding as short YES). `marketMetadata.outcome`, when present, is honoured exactly as `_position_leg` honours it; a sign/outcome contradiction is **undetermined** (`None`, stays AMBIGUOUS), never guessed.
3. **AC3 (per-intent fail-closed guard).** The slug/leg/holding derivation sits inside a `try`. Any exception is recorded through the existing `self._note_resolver_error(context.intent_id, exc)` (`client.py:4367`: counts `_resolver_error_count`, logs ERROR once per intent), then `continue`. The periodic task stays alive and the next pass runs.
4. **AC4 (resolution outcomes).** A NO-leg terminal GET with `cum == 0` and no NO holding retires `STATUS_REPORT_ZERO_FILL_TERMINAL`. A NO-leg terminal fill with `netPosition < 0` on the base slug resolves through `_resolve_accept_fill` (no deadlock). YES-leg behaviour is unchanged except that a YES `outcome`/sign contradiction now reads as undetermined instead of "no LONG" (a fail-closed tightening, stated and tested).
5. **AC5 (gates).** `scripts/ci/run_tests_no_egress.sh` passes in full; `lint-imports` passes. The egress guard `EXEC_RESOLVER_PERMITTED_CALLEES` (`tests/unit/test_execution_egress_firewall_guard.py:2081`) changes by exactly the reviewed rows in §5 and nothing else; `self._order_sender.post_order` stays absent.

## 2. Evidence and root cause (file:line, verified 2026-09-27)

- `exec/client.py:2419-2420`:
  `slug = instrument_id_to_slug(instrument.id)` then `long_state = _resolver_long_position_state(positions, slug)`. Both sit **after** the positions-read `try` (`:2409-2417`) closes and **before** the action `try` blocks (`:2437-2455`). Nothing wraps them.
- `instrument_id_to_slug(no_leg_instrument_id(slug))` raises `VenuePayloadError: … contains the reserved instrument separator '^'` (reproduced live in the EDGE-2 r1 session). `base_slug_of`'s own docstring (`symbology.py:298-306`) says it is "the ONLY sanctioned way to read a slug off a NO id".
- Blast radius of the raise:
  - Periodic task (`client.py:1775`, `self.create_task(self._resolve_ambiguous_intents())`): the exception leaves the `while True` loop; Nautilus's `_on_task_completed` only logs it. The resolver is dead for the process lifetime.
  - Boot pass (`client.py:1755`, `first_pass_immediate=True`): caught at `:1756-1760` as a WARNING, then the periodic task is started — and dies on its first pass the same way.
  - The account-wide `SubmitIntentLatch` stays OPEN, so every order is denied until an operator clears it by hand. That is the L-48 deadlock class.
- `_resolver_long_position_state` (`client.py:1317-1336`) returns `net > 0` only. A NO holding (short YES on the base slug) reads as "no LONG", so a NO-leg terminal **fill** falls into the disagree branch (`:2456-2461`) forever — a second, quieter deadlock even once the raise is gone.
- No NO-leg with-id AMBIGUOUS has happened yet (resolver contexts `428709da` MIA 09-13 and `5af9eba3` SFO 09-11 are YES). The defect is latent and armed for the first NO-side AMBIGUOUS after re-arm.
- Existing primitives, all reused: `base_slug_of`, `leg_of` (imported `client.py:324-326`); `_position_leg` (`reports.py:1426`); `_note_resolver_error` (`client.py:4367`, already on the resolver allowlist at guard `:2174`).

## 3. Options and trade-offs

| # | Option | Verdict | Why |
|---|---|---|---|
| 1 | `base_slug_of` + leg-aware holding reusing `_position_leg`'s rule + one local `try` | **CHOSEN** | Smallest correct change; reuses the sanctioned helper and the ruled leg semantics; no new venue read. |
| 2 | Wrap only the `instrument_id_to_slug` call in a `try` | Reject | Stops the crash, but every NO intent then errors on every pass and never resolves — the deadlock moves, it does not go away. |
| 3 | Re-implement the sign rule inline (`net < 0` for NO) | Reject | Duplicates `_position_leg`, and silently ignores `marketMetadata.outcome`, which the 09-16 ruling made authoritative. |
| 4 | Loop-wide `try/except` around the whole pass body | Reject | Broad catch hides future defects in unrelated branches; the ruling asks for a per-intent guard at the known failure site. |

**Nautilus null hypothesis (L-1).** Not applicable to a native capability: the defect is inside Breezy's own resolver coroutine, which exists because the native in-flight poller is disabled (`runtime/node_config.py:689-712`) and native reconciliation cannot join this venue's orders (L-36). The fix changes Breezy code only.

## 4. Architecture and data flow

```
resolver pass, after a terminal / fill GET and an eof-complete positions read:
  try:
      leg       = leg_of(instrument.id)                 # "yes" | "no"
      base_slug = base_slug_of(instrument.id)           # accepts both legs
      held      = _resolver_long_position_state(positions, base_slug, leg)   # True | False | None
  except Exception as exc:
      self._note_resolver_error(context.intent_id, exc); continue   # AC3
  held is None  -> stay AMBIGUOUS (unchanged)
  terminal-zero and held is False -> _resolve_terminal_zero   (unchanged)
  fill          and held is True  -> _resolve_accept_fill     (unchanged)
  else          -> disagree WARNING, stay AMBIGUOUS           (unchanged)
```

`_resolver_long_position_state(positions, slug, leg)` keeps its name ("long" is correct: per the ruling a NO holding is a LONG on the NO-leg instrument), gains a required `leg` argument, and becomes:
- slug absent → `False`; payload not a mapping, `netPosition` absent or unparseable → `None` (unchanged);
- `net == 0` → `False`;
- otherwise `held_leg = position_leg(net=net, metadata=payload.get("marketMetadata"), context=…)`; `ExecutionReportMappingError` (outcome/sign contradiction or unknown outcome) → `None`; else `held_leg == leg`.

`position_leg` is `_position_leg` exposed under a public name in `reports.py` (a rename with the private name kept as an alias for its existing callers, or a one-line public wrapper — implementer's choice, behaviour byte-identical). `client.py` already imports from `reports`; `lint-imports` confirms. `_resolver_long_position_state` is a module-level function, not a scanned coroutine, so `position_leg` needs no guard row.

Clearing path (L-48 row): the latch is the account-wide OPEN intent; it is cleared by this resolver on the first pass whose GET + positions evidence agree, which AC4 now makes reachable for the NO leg. A derivation error never ends the task, so the next pass is always another chance to clear it; `breezy-clear-submit-intent` remains the operator exit for a persistently undetermined read.

## 5. File-by-file plan

| File | Change |
|---|---|
| `src/breezy/adapters/polymarket_us/exec/client.py` | `:2419-2420` → the guarded block in §4. `_resolver_long_position_state` (`:1317`) gains `leg` and the leg-aware body. Its docstring and the `_resolve_ambiguous_intents` docstring paragraph at `:2093-2098` updated to "leg-aware `netPosition` sign per `_position_leg`". Remove the `instrument_id_to_slug` name from the `symbology` import at `:325`: `:2419` is its only call site in `client.py` (verified), so ruff F401 would otherwise fail. |
| `src/breezy/adapters/polymarket_us/exec/reports.py` | Public `position_leg` for `_position_leg` (behaviour byte-identical; existing callers untouched). |
| `tests/unit/test_execution_egress_firewall_guard.py` | `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2081`): **add** two reviewed rows, `"base_slug_of"` and `"leg_of"`, each with a comment citing this plan (pure symbology helpers: no I/O, no await, no sender reference). **Remove** `"instrument_id_to_slug"` (`:2124`) because the resolver no longer calls it — a narrowing, never a relaxation (L-12). `_resolver_long_position_state` and `self._note_resolver_error` are already listed. No other list changes; `post_order` absence assertions untouched. Run the guard unmodified first and confirm it demands exactly these two rows. |
| `tests/unit/test_current_rung_hold_ambiguous_resolver.py` | RED tests of §6. |

## 6. Test strategy (RED first)

All in `tests/unit/test_current_rung_hold_ambiguous_resolver.py` unless noted. Fixtures are synthetic, derived from the captured positions shape (`docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/positions_all.json`, names only) and the existing YES resolver fixtures; the NO instrument is built with `no_leg_instrument_id`.

1. `test_no_leg_terminal_get_does_not_raise_on_reserved_separator` — NO instrument, GET `EXPIRED qty=1 cum=0 leaves=0`, positions `{}` eof. RED today (`VenuePayloadError` at `:2419`). GREEN: no exception, intent RETIRED `STATUS_REPORT_ZERO_FILL_TERMINAL`.
2. `test_no_leg_terminal_fill_with_short_yes_net_resolves_accept_fill` — GET terminal fill, `positions[base_slug].netPosition < 0`. RED today (raise, then disagree). GREEN: durable `fill/<id>`, RETIRED `STATUS_REPORT_ACCEPT_FILL_TERMINAL`.
3. `test_no_leg_positive_net_on_base_slug_is_not_a_no_holding` — NO order, `net > 0` on the base slug → `False`; a terminal fill stays AMBIGUOUS (disagree WARNING).
4. `test_no_leg_outcome_no_with_negative_net_is_a_no_holding` — `marketMetadata.outcome="No"`, `net < 0` → `True`.
5. `test_holding_outcome_sign_contradiction_is_undetermined_for_both_legs` — `outcome="Yes"` with `net < 0`, and `"No"` with `net > 0` → `None`, stays AMBIGUOUS, no retirement.
6. `test_yes_leg_holding_semantics_unchanged` — regression matrix: absent → `False`, `net > 0` → `True`, `net == 0` → `False`, `net < 0` → `False`.
7. `test_malformed_net_position_stays_ambiguous_for_both_legs`.
8. `test_slug_derivation_failure_is_logged_counted_and_resolver_keeps_polling` — an instrument whose venue is not `POLYMARKET_US` (so `base_slug_of` raises `VenuePayloadError`). Asserts `_resolver_error_count` +1, one ERROR line, intent still OPEN, and a second pass runs (the periodic task is not `done()`).
9. `test_periodic_resolver_task_survives_a_no_leg_pass` — drives the real periodic task (poll interval shrunk) over a NO-leg pass; asserts the task is still running afterwards.
10. Egress guard (`tests/unit/test_execution_egress_firewall_guard.py`): passes with exactly the §5 rows.

Run: focused file, then the egress guard file, then `scripts/ci/run_tests_no_egress.sh` (basetemp under `/home/jon/.cache/breezy-gate/`), then `lint-imports`; read exit codes.

## 7. Execution order and parallelism

Single slice, single worktree (`PYTHONPATH=<wt>/src`, `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`). Implementer: `tdd-guide` seeded with python-testing. Reviewers: `python-reviewer`, `silent-failure-hunter`, `security-reviewer` (guard rows). It can run in parallel with anything else; it touches `client.py:1317-1336` and `:2419-2420` only, so EDGE-2 r2 rebases onto it.

## 8. Deploy and verification

- Node code: live on the **next node respawn**; never kill the live node. Supervisor untouched.
- Proof it is live: the node log FILE at `_connect` carries the new commit's code (check the respawn's boot line / git sha convention used by prior deploys) and no `immediate resolver pass failed` WARNING at boot.
- Behavioural proof is test-only while the A1 halt is SET (no orders → no AMBIGUOUS). Add a PROGRESS.md `EDGE-2C-LIVE` watch row: the first NO-leg with-id AMBIGUOUS after re-arm must end RETIRED by the resolver, with no `resolver: acting on intent … raised` ERROR.

## 9. Risk register

| Risk | L | I | Mitigation |
|---|---|---|---|
| `parse_order_status_report` maps a NO-leg GET price differently from the create path, so `_resolve_accept_fill` books a wrong cost | L | H | Out of this slice's change (S5 merged the NO-leg mapping, `_order_side_for_leg`). Test 2 asserts the synthesized `cumulative_cost` equals `cum × avgPx` on the NO fixture; a mismatch is a separate finding. |
| YES behaviour changes on an outcome/sign contradiction | L | L | Direction is fail-closed (undetermined, stays AMBIGUOUS). Test 5. |
| An exit (closing) order that fully filled leaves no holding, so `held is False` with a GET fill → disagree forever | M | M | Pre-existing and leg-independent; out of scope here. EDGE-2 r2 slice D's activities join ("fill ∧ (held ∨ trade-for-id)") is the fix; recorded there. |
| Guard change mis-scoped | L | H | Two added rows, one removed, each reviewed; `post_order` assertions untouched. |

## 10. LESSONS and invariant compliance

- **L-48** clearing-path row in §4; tests 1, 2, 8, 9 drive it. **L-12** exact-set widened by reviewed rows only. **L-36** the GET stays the authority. **L-1** §3.
- Nautilus untouched; `allow_short` stays `False`; no operator cap read or assigned; live enablement and the A1 halt untouched; no venue call; no store written by hand.

## 11. Dependencies on other EDGE items

- Depends on: none.
- Depended on by: EDGE-2 (r2, by ID), EDGE-5 re-arm roadmap (HARD precondition), any A1-class re-arm ruling.

## 12. Confidence

HIGH (~90%). The raise site, the unwrapped region and the helper are verified from source. Unknowns: (1) whether the egress guard has a staleness check that also demands the `instrument_id_to_slug` removal — either way the change is a narrowing; (2) the exact public spelling of `position_leg` (implementer's choice, behaviour pinned by test 6).
