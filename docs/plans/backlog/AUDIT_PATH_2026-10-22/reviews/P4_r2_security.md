# P4 r2 verification — security-reviewer

**VERDICT: APPROVE-WITH-CHANGES.** Items 1, 2, 3 and 7 are resolved. The "no rename, no new manifest" premise holds, but there is one gap in the manifest edit. Confidence 80.

**Moot items 4–6 are really moot, with one correction**
- `deploy/families/pm_us_no_maker_sharp_v1.json` already exists, with composition kind `no_ladder_maker` and stations LAX, MDW, MIA and SFO. `FAMILY_ID` in `harm_stop_artefact.py` already matches it. So no rename is needed, and the loss-stop unit and halt CLI already use that id.
- The manifest does need an edit. It has no `live_orders_ruling` field today (family_manifest.py:270 defaults it to None; the field is only declared on the FQ manifest).
- Without that field, `live_orders_authorized` returns `no_ruling` and the family stays shadow, even with a correct allowlist row. The pre-ARM table lists the `d0_climate_day` edit but never lists adding `live_orders_ruling` to the manifest. See change 1.

**Items 1, 2, 3 and 7**
- **Lag exposure (resolved).**
  - Step 5 uses the right inputs: the 12:50Z producer and the 48h PENDING window.
  - The ceiling of about $21 holds. The ladders are 4 stations × `max_rungs=2`, so at most about 8 fills a day, and 8 × 0.89 × 3 days is a fair bound.
  - The GTD orphan bound is cited correctly (`rule.py:231`).
- **Per-order cancel and open-orders-zero check (resolved).** The stop procedure now says per-order cancel, a venue open-orders listing with zero on our slugs, and `set_family_halt_cli` used additionally and never alone. It no longer relies on slug cancel-all, which B2 showed leaving a sibling order live.
- **Rollback (resolved).** It restores the drop-in together with its `DROPIN_ALLOWLIST` row and its test, then stops the node and confirms DISPOSED. The `KillMode=process` point is correct (supervisor unit, line 163).
- **Arming relaunch (resolved).** Step 6 stops the node, confirms DISPOSED, then relaunches via `systemd-run --user`.
- **S2/C7 commit (resolved).** It is a separate commit that lands before the merge, with the pin kept green.
- **Exactly one ruling file (resolved).** One file, with its sha pinned in the allowlist row. The ruling file name `RULING_MAKER_sharp_v1_live_small_2026-10-21` must be created under `deploy/families/rulings/`, not `docs/evidence`.

**Statistics check:** P(PASS | p=0.875) = 0.0449, P(PASS | 0.95) = 0.44, and the ≤1 loss in 37 station-days design all recompute correctly.

**Required changes**
1. **Add the manifest edit to step 3 or 4.** Set `live_orders_ruling` and the real `d0_climate_day` on `pm_us_no_maker_sharp_v1.json`. Note that the family-manifest golden and marker tests will see the changed bytes.
2. **Name the guard test that flips.**
   - `tests/unit/test_no_ladder_maker_wiring.py:69` asserts "live sending is off: no ruling, no allowlist row, no drop-in row". It will go red by design.
   - Update it to assert the new intended state. Do not delete or weaken it.
   - Do the same for `test_unit_health_dropins.py`, which unpacks a single allowlist row (`(row,) = DROPIN_ALLOWLIST`, line 117).
3. **The "2nd loss means FAIL and halt at once" rule is manual.**
   - D1 halts automatically only at the 3rd loss, and it is checked once a day with a 48h settlement lag.
   - The 2nd-loss halt therefore depends on someone reading the artefact, and fills continue meanwhile.
   - State that the halt is a manual `set_family_halt_cli` action, or accept the extra lagged exposure explicitly. This is MEDIUM, since the money bound is still the $21 ceiling.

**MEDIUM**
- The plan wants a fresh harm-stop PASS before ARM. A HOLD writes no file, so check the artefact exists after the first producer run.
- The breakeven of 0.875 is a number to compute once from the in-sample positions and pin in the ARM commit, as the plan says.
- The caps are untouched: the plan only reads the daily-spend ledger and sets no cap.

No new CRITICAL or HIGH issues.