# PREREG v3 — continuous_rung_hold (Polymarket.us) — Phase 1 + Phase 0b continuous hunt (BINDING, registered 2026-09-11)

**Status: BINDING (registered 2026-09-11 UTC; D0 = 2026-09-12 climate_day per §1)**

This spec registers **Phase 1** (continuous hunt with bounded AMBIGUOUS-intent resolution) and **Phase 0b** (extended hunt triggers) as a CLASS (C) new family — v2's trigger selection is frozen; v3 is a different selector. Reuse v2's sequential monitoring rule, `I_max=40`, `n_max=160`, LD-OBF α=0.025 per side, and all strata unchanged from v2 rev b. No change to `allow_short` (stays `False`), Nautilus, or v1's byte-identical code.

---

## 1. Family Registry

| Property | Value |
|---|---|
| `family_id` | `pm_us_crh_cont` |
| `venue` | `polymarket_us` |
| `trial_id_prefix` | `continuous_rung_hold/trial/` |
| `stations` | LAX, MDW, MIA, SFO |
| `status` | REGISTERED (2026-09-11 UTC) |
| `d0_climate_day` | **2026-09-12** (pinned at registration 2026-09-11, before first fill) |
| `boundary_artefact_path` | `deploy/families/gs_boundary_pm_us_crh_v2.json` (reused verbatim, §16) |

---

## 2. Selection Population (Phase 0b and Phase 1)

**Trigger.** First FILLED legal snapshot under continuous hunt on EVERY eligible QuoteTick AND EVERY OrderBookDepth10 ask update.

- **Phase 0b (shadow, permit=None):** hunt evaluates on every Depth10 ask update. Shadow trials never feed a verdict; replay is characterisation only, never a verdict.
- **Phase 1 (live, bounded permit restoration):** hunt continues on both QuoteTick and Depth10; de-duped against the same frame.

**Covariates, NOT H0 conditioning (L-18):** first-executable ask, rung, m_code, hour_lst (LST). Trial is the first eligible snapshot; re-evaluated on later rungs and Depth10 asks to maintain continuous hunt.

**Strata.** Same as v2: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead). No venue stratum.

---

## 3. Decision Rule (unchanged from v2, with AMBIGUOUS-resolution gate)

Under H0, `held_i | ask_i ~ Bern(BE_i)` with `BE_i = entry_ask_i + fee_i` per row (v2 §5). Fill-conditional: filled Takes only; interior `m=1` stays illegal (strategy/current_rung_hold/decision.py:236–247,287–288).

**Sequential monitoring** (v2 rev b §3–4):
- `S_k = Σ_i (held_i − BE_i) / sqrt(Σ_i BE_i(1−BE_i))`
- `I_k = Σ_i BE_i(1−BE_i)` (observed statistical information)
- `t_k = min(1, I_k / I_max)` where `I_max = 40` (fixed constant)
- Look schedule: every 10 filled Takes (`n_k = 10, 20, …, 160`)
- Boundary solver: LD-OBF, two one-sided α=0.025, information fraction `t`
- Efficacy stop: `S_k ≥ b_k^eff` AND `total_pnl > 0` AND no cell_dead → **SURVIVE** (where `total_pnl = scored_pnl − residual`, residual an unsigned loss magnitude, §5)
- Futility stop: `S_k ≤ b_k^fut` OR cell_dead OR (`b_k^fut < S_k < b_k^eff` at terminal look) → **KILL**
- Truncation at D0+165 or `total_pnl ≤ −60` (contract-unit halt, §5, v1/v2 registered in contract-units per §7)

**No change to v1's terminal Wilson bounds or frozen parameters** (v2 rev b §2,7).

---

## 4. AMBIGUOUS-Resolution Gate (Phase 1 — new)

**The problem.** `create_order` response never carries `cumQuantity` or terminal `state`; an IOC with `executions: []` after ~5.2 s (maxBlockTime ≈ 5 s) is indistinguishable from a venue-timeout shape. Permit restoration and continuous hunting require a bounded, fail-closed resolution.

**Mechanism (Phase 1, exec client, client.py):**
1. On every NO-FILL IOC, record durable store `exec/polymarket_us/resolver/{intent_id}` with `(venue_order_id, instrument_id, client_order_id, notional_usd, booking_id, created_ns)` *before* resolver can act.
2. Launch `_resolve_ambiguous_intents()` task (started from `_connect` after `_open_state_store()`, added to `EXEC_PERMITTED_COROUTINE_NAMES` guard and pinned constants; see Resolution A pins below).
3. For each OPEN intent, issue a **bounded GET `/v1/orders/{venue_order_id}`** until terminal status or max retries.
4. **GET-FILLED path (no execution legs, `fee_reconciled=False` by construction):** record the fill, true up, retire intent, emit `generate_order_filled`, flag for residual scoring.
5. **GET-terminal (CANCELED/EXPIRED/REJECTED) + `filled_qty==0`:** true up booking to ZERO, retire intent, restore ONE permit slot, clear IN_FLIGHT.
6. **GET-unreadable or network failure:** retry with jittered backoff; intent stays OPEN, hunt defers.
7. **Retire gate (SAFETY H2):** hold in-memory `resolved_by_get_ts_ns: dict[str, int]`, set only by a terminal GET in THIS process run. Durable key never authorizes retirement; a stale key from a prior restart cannot retire anything.
8. **Double-retire prevention (SAFETY M2):** `_retire_unlocked` raises `SubmitIntentMismatch` when singleton is not OPEN with matching id (runtime/submit_intent.py:441–450). Re-entry reads `current()` first; does not call `retire` if already retired with that id.

**With-id retirement.**  The new retire caller (AMBIGUOUS resolver) retires with a venue `order_id`; the existing create-body retire path stays byte-unchanged. The classifier remains: first-match (`duplicate_fill`, else `q≠1`, else fee-unreconciled) per fill.

**Clear_submit_intent remains the only no-id path** — operator-visible, manual AMBIGUOUS clearing for edge cases where GET is unreachable.

---

## 4a. Resolution H — L-32 / R-7 §5 Ruling (plan rev 5 Resolution H, carried unchanged into rev 6.1)

> **L-36 (ruling).** R-7 item 5 and L-32 pin the interpretation of the **create-order response body**: `200` + `id` + `executions == []` with no terminal `state`/`cumQuantity` stays KIND_AMBIGUOUS, and `classify_create_order_outcome` (`exec/submit_chain.py:818-855`) is byte-unchanged — the pin `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking["200-id-no-exec"]` (`tests/unit/test_polymarket_us_submit_order_chain.py:593-620`) must keep passing and must not be reused as a resolver test. A subsequent `GET /v1/order/{id}` is a **new evidence source**, not a reclassification. `_resolve_ambiguous_intents` is hereby a **new retire caller for an AMBIGUOUS OPEN intent, with a venue order id only**, using `RetirementReason.STATUS_REPORT_ZERO_FILL_TERMINAL` (new member, `runtime/submit_intent.py:73-78`) or `ACCEPTED_WITH_DURABLE_FILL`. B10 still holds: `clear_submit_intent` is not invoked and stays the only no-id path (`runtime/clear_submit_intent_cli.py:130-138`). R-7 item 5 "exit is the clear tool" is superseded **for the with-id class only**. Fail-closed: GET failure, 5xx, malformed, PENDING, not-found and retry exhaustion are never terminal evidence.

---

## 5. Residual Classification & Contract-Unit Halt (Phase 1 — new)

**Definition: `total_pnl` (efficacy gate § 3, halt sum § 5).** Identical computation, passed to `look_verdict` / `terminal_look` (src/breezy/settlement/current_rung_hold_v2.py) as `total_pnl = scored_pnl − residual`, in contract-units (not dollars); `residual` is an UNSIGNED loss magnitude (§5), so it can only move `total_pnl` toward KILL, never toward SURVIVE (`scripts/analysis/family_tally_v2.py::v3_residual_from_fill_source` negates the magnitude before it is added). This is the quantity monitored for SURVIVE (`total_pnl > 0`), KILL (`total_pnl ≤ −60`), and futility boundaries. v1/v2 register in contract-units per §7.

**Residual is THREE mutually exclusive per-fill buckets; classification is FIRST-MATCH-WINS:**

1. **`duplicate_fill`** — second genuine fill on an already-consumed station-day (distinct `venue_order_id`). This short-circuits; the next two checks never apply.
2. **`q≠1`** — partial or multi-fill; only full-contract fills score.
3. **`fee_unreconciled`** — fill's execution legs do not sum to recorded fee. Includes resolver GET-FILLED (no legs, `fee_reconciled=False` by construction).

Every unscored fill contributes to EXACTLY ONE bucket. Residual = sum of `qty × (fill_px + fee)` over all buckets — an UNSIGNED magnitude, always ≥ 0, SUBTRACTED from `scored_pnl`.

**Family halt on duplicate fill (fail-closed):**
- On-fill: write `continuous_rung_hold/family_halt/duplicate_fill` (same flock as latch).
- On-start or future _hunt_tick: check halt key; if present, zero arms for this family until operator-visible clearing.
- Recon-replay idempotent: same-`venue_order_id` fill never creates bucket or halt.

**Contract-unit halt (LOSS_STOP):**
- **KILL if `total_pnl ≤ −60` (contract-units)** where `total_pnl = scored_pnl − residual`.
- This halt is NOT inside the operator's daily-budget cap (named only in env; never valued in code).
- Re-arm floor: `_REARM_MIN_DELAY_SECS = 120` (documented conservative floor, build-side constant, unverified until first `PositionReportingLag` record in live fills).
- Re-arm gate: evidence-based (fresh eof-complete positions read showing no LONG on instrument).
- Attempt counter: `_MAX_STATION_DAY_ATTEMPTS = 3`, frozen by `is_consumed` (no re-arm after a fill).

---

## 6. Safety Pins (Phase 1)

### Pre-arm race (SAFETY-C1) — authoritative re-check inside `_submit_order`

Two stations drained in one burst produce two independent `_submit_order` tasks. The strategy-level pre-check (`_hunt_tick`, line 237–238) runs BEFORE `set_inflight`; both tasks can observe `is_intent_open() == False`. Permit is spent at client line 1590–1601 (inside `assert_live_order_submission_permitted`), before `arm` at line 1613.

**Fix: insert authoritative check at line 1588–1589** (after `permit_is_missing` deny, before spend):
```
if self._latch is not None and self._latch.is_latched():
    return self._deny(order, submit_chain.OPEN_INTENT_WAIT_REASON, now_ns)
```

This runs on the same event-loop thread as `arm`, with no `await` between them, so no second task can interleave. `is_latched()` reads the OPEN singleton under the same flock. On WAIT, strategy calls `clear_inflight(station, day)` → station re-hunts on a later tick. WAIT is not a refusal.

**Pins:**
- `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` equality re-asserted with exactly two additions: `self._note_ambiguous_open` and `self._latch.is_latched`.
- New pin: await exemption in guard line 1986 (`node.name != "_submit_order"`) remains live — an `await` in `_cancel_order` yields E0-NOSEND; same `await` in `_submit_order` does not.

### Never-arm startup gate

`read_startup_position_evidence()` on exec client returns `(refusal_free, eof_complete, fill_walk_complete, positions_by_instrument)`. All three flags must be True or startup halts and never arms. Phase 1, not Phase 0b.

---

## 7. Operator Controls (exactly two budget caps)

| Control | Location | Scope |
|---|---|---|
| Daily budget cap | `operator.env` (gitignored, memory/shell-only) | Account-wide per session |
| Per-position cap | `operator.env` (gitignored, memory/shell-only) | Per-station-day notional |

No other operator variable. Enablement flags, PREREG status, session ceilings, operator ID are build-side derived or constant. Dollar halt KILL is named only; its −60 contract-unit threshold is never configurable.

---

## 8. Boundary Artefact (unchanged from v2)

`deploy/families/gs_boundary_pm_us_crh_v2.json` (reused verbatim — identical design, see §16; inputs sha `471fd8a7…c150e0c`) pins:
- Inputs: two one-sided α=0.025, LD-OBF spending of `t`, look schedule `n_k = 10..160` step 10, `I_max=40`.
- Solver: `b^eff(t)`, `b^fut(t)` functions, not fixed 16 z-values.
- Regression fixture: equal-`t` 16-row table only (test fixture, not operative).

---

## 9. Structural-Dead Test (unchanged from v2)

Window `[12:00, 17:00)` LST, 30 min afternoon-covered threshold, ≥15 covered listed station-days denominator. Separate from D0+165 clock stop.

---

## 10. Frozen from v2 (unchanged)

- `n_max=160`, `I_max=40` (theoretical Bernoulli bound)
- Per-row `BE_i = ask_i + fee_i` (concave-fee amendment)
- Sequential monitor `S_k`, `I_k`, `t_k`
- LD-OBF boundary solver, two-sided α=0.025, spending function of `t`
- Wilson terminal endpoints (never sequentialized)
- Fixed strata: pooled (sequential), station (cell_dead@n≥60 vs `mean(BE_i)`), ask-band (cell_dead)
- No venue stratum; no `venue` column on `ScoredTrial`
- `v1 byte-identical` (live_family_tally.py, all v1 paths untouched)
- D0 climate_day discriminant (LST station-day, not UTC fill timestamp)
- Kalshi sibling never pooled; own PREREG, own D0
- `fee_schedule_mismatch` remains a per-tick admission Refuse (v1/v2 unchanged, decision.py:268–269 / tick_eval.py:76–77) — not a family halt; only duplicate_fill (§5) is.

---

## 11. Implementation Gaps & Artefacts (Phase 0b and Phase 1)

| Item | Module | Status |
|---|---|---|
| Depth10 hunt path | ContinuousRungHoldStrategy.on_order_book_depth | Phase 0b: implement + test |
| De-dupe QuoteTick vs Depth10 same-frame | parsing.py, decision.py | Phase 0b: ts_event identity + DataEngine topic routing |
| `_resolve_ambiguous_intents` task | client.py | Phase 1: new coroutine, guard pins |
| `_note_ambiguous_open` durable write | client.py | Phase 1: store key before resolver |
| AMBIGUOUS resolver GET + retry | client.py | Phase 1: bounded, jittered backoff, fail-closed |
| `_retire_unlocked` raise on non-OPEN singleton | runtime/submit_intent.py | Phase 1: line 441–450 (already exists) |
| Duplicate-fill bucket + family halt | strategy.on_order_filled, trial_day_latch.py | Phase 1: `record_duplicate_fill`, halt key write |
| `PositionReportingLag` record type & emission | resolver path | Phase 0b: record type; Phase 1: emission plumbing (values require live fill) |
| Dollar halt KILL condition | family tally | Phase 1: check scored_pnl − residual ≤ −60 |

---

## 12. Acceptance Criteria (Phase 0b and Phase 1)

**RED→GREEN tests required before d0 registration:**

1. Hunt evaluates on Depth10 ask updates; de-duped against QuoteTick same-frame.
2. Two stations, one burst, one permit slot spent; passes with `_hunt_tick` pre-check disabled (verifies authoritative check at line 1588–1589).
3. WAIT deny clears IN_FLIGHT and latches no refusal.
4. Restart re-entry never retires without a terminal GET in that run (+ mutation test).
5. Re-entry against already-RETIRED singleton calls `retire` zero times; cleans up.
6. Duplicate fill → bucket + halt; replayed same-id → neither.
7. `is_consumed` freezes the attempt counter.
8. Guard pins: order-path allowlist grows by exactly two names; await exemption still `_submit_order`-only.
9. Residual classification mutually exclusive: GET-FILLED duplicate contributes to `duplicate_fill` only; counted once; never in fee-unreconciled or `q≠1` buckets.
10. Dollar halt fires when `scored_pnl − residual ≤ −60`; family stops arming.
11. Re-arm gate is evidence-based (eof-complete positions read); attempt counter blocks re-arm after fill.

---

## 13. Contested & Unverified

**Contested framing only (carried from v2):**
- SAFETY C1's alternative ("move permit spend after `arm()`") reorders R-7 chokepoint and is rejected. Authoritative check is the chosen fix.
- MARKET's "2× position bound" is replaced by halt mechanism for duplicate fill; construction bound is one position per station-day.

**Unverified (Phase 0b will produce evidence):**
- GET-fill `TradeId` uniqueness; `venue_order_id` non-reuse across orders.
- `parse_quote_tick` vs `parse_order_book_depth10` `ts_event` identity (read parsing.py before de-dupe).
- DataEngine topic routing (strongly implied, not verified).
- Live `minimumTradeQty` and in-window quote rate.
- 120 s re-arm floor (unverified until first `PositionReportingLag` record with live fill).
- Phase 1 only: bounded GET retries sufficient; venue 5xx / 404 wire shapes.

---

## 14. Reference (unchanged from v2)

- Statistic: v2 rev b §3, ruling `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md` option (C).
- Truncation & spending: v2 rev b §4.
- Strata & cell_dead: v2 rev b §5–6.
- Boundary solver: v2 rev b §7.
- D0 rule: v2 rev b §8.
- Structural-dead test: v2 rev b §9.
- Settlement module: `src/breezy/settlement/current_rung_hold_v2.py:1–130` (sequential rule, `break_even_row`, `score`, `information_fraction`, `look_verdict`, `terminal_look`).
- Lessons: L-18 (counterfactuals are mechanism claims), L-32 (search prior ruling), L-34 (trigger is pinned), L-35 (Depth10 for empty books).

---

## 15. Changelog (rev 6 Phase 0b/1 merge)

**Phase 0b (shadow, Phase 0 fixups):**
- Depth10 hunt triggering on every ask update, de-duped vs QuoteTick same-frame.
- `PositionReportingLag` record type (emission plumbing Phase 1).
- Never feeds verdict; replay is characterisation only.

**Phase 1 (live order gate + AMBIGUOUS resolution):**
- `_resolve_ambiguous_intents` bounded GET loop with fail-closed retire.
- AMBIGUOUS with-id retirement (+ clear_submit_intent no-id path unchanged).
- Pre-arm race SAFETY-C1 authoritative check (two new guard pins).
- Duplicate-fill residual bucket + family halt (MARKET C1).
- Dollar halt KILL if scored_pnl − residual ≤ −60 (not inside daily budget cap).
- Re-arm evidence gate + attempt freeze by `is_consumed`.
- Residual mutually exclusive per-fill classification.

---

## 16. Registration record (2026-09-11)

Registered 2026-09-11 UTC per operator delegation (strategy-lead ruling via `docs/evidence/`
decision artifacts; domain-reviewer approval contingent on Phase 1 order enablement and AMBIGUOUS
resolution).

- **D0 = 2026-09-12** (UTC climate_day; first UTC day strictly after this registration commit,
  never retroactive). `deploy/families/pm_us_crh_cont.json` carries `status: "REGISTERED"` and
  `d0_climate_day: "2026-09-12"`.
- **Registration commit.** registration commit: <sha to be filled by coordinator at commit>
- **Boundary artefact reused verbatim.** `deploy/families/gs_boundary_pm_us_crh_v2.json` is
  authoritative -- this family does NOT build its own artefact; the identical sequential design
  (LD-OBF, α=0.025, n_max=160, i_max=40, look_step=10) means the artefact's `inputs_sha256`
  covers this family's inputs exactly as it covers v2's (`scripts/analysis/
  crh_group_sequential_boundaries.py` `inputs_manifest` -- alpha/spending_function_id/n_max/
  i_max/look_step only, no data).
  `boundary_inputs_sha256 = 471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c`.
- **Fill-time look ordering.** `ScoredTrial` carries no fill timestamp; `score_live_trials.py`
  appends `(trial_id, score_seq) -> filled_at_ns` sidecar; `family_tally_v2.py` replays in real
  fill-time order.
- **Provenance sidecar.** `score_live_trials.py` writes `<store_dir>/provenance.json = {"provenance":
  "live"}`; tallies refuse stores lacking it or declaring anything else (except empty stores before
  first fill).
- **`q != 1` exclusion.** Fills with `qty != 1` excluded before scoring.
- **`held == (pnl > 0)` guard.** Scored rows where `held` disagrees with `pnl` sign refuse tally.
- **Empty-store rule.** Stores with no rows and no provenance report `n=0`/CONTINUE; stores with
  rows and no/mismatched provenance refuse fail-closed.
- **Phase 1 additions.** AMBIGUOUS with-id retirement via bounded GET resolver
  (`_resolve_ambiguous_intents`, exec/client.py:1068-1267); no-id AMBIGUOUS operator-only
  (`breezy-clear-submit-intent`). Duplicate-fill halt stops arming family-wide.

---

**Generated: 2026-09-10 | Registered: 2026-09-11 (D0 = 2026-09-12) | Files scanned: 5 inputs | Status: BINDING**
