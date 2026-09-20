# Post-forecast phase — plan of record

**Date:** 2026-09-20. **Status:** DRAFT, pending adversarial peer review.
**Context:** three hypotheses died on 2026-09-20; the bot has not traded since
2026-09-17. This plan covers getting back to a state where the bot can trade
*or* is honestly retired, and where we would KNOW if it stopped.

## 0. Established facts (measured; not to be re-litigated)

1. **Forecast taker — DEAD.** `RULING_forecast_edge_programme_closes_2026-09-20.md`.
   Murphy decomposition, 384 rung-events / 64 clusters: forecast resolution
   0.01554 vs market 0.03072; `D = −0.01518` CI95 [−0.03229, −0.00373]. The
   market ranks ~1.98× better. LOSO recalibration does not help.
2. **Maker (v5) — DEAD as drafted.** `PREREG_v5:5` — entry thesis and
   confirmatory statistic "UNCHANGED from v3". `G-R4`: resting −2.550 vs IOC
   −2.09. It loses more than the baseline it must beat, and its only modelled
   fill channel is the adverse one. **Folded to `CLOSED_NOT_REGISTERED`.**
3. **Overconfidence-fade — UNDETERMINED and unmeasurable.** Reliability gap is
   real and sign-stable (ask ≥ 0.70 dev −0.6389 CI [−0.8233, −0.3823]) but
   driven by overround mislabelled as belief (mean Σask 2.3516 on carrying
   ladders; SFO 09-01 Σask = 3.90). **The NO leg has never been priced** —
   `order_book_depths` / `quote_tick` / `trade_tick` hold ZERO `^no` dirs.
4. **The bot is halted fail-closed on a fee ruling.** θ 0.06 → 0.0695 on
   09-17; last strategy line is `FEE_SCHEDULE_MISMATCH_REFUSALS`.
   `FEE_SCHEDULE_PIN_2026-09-18.md` forbids an in-place pin edit.
5. **The permit lapses ~14 h/day.** Minted once (`safety.py:675`, one caller
   `app/trade.py:379`), `PERMIT_TTL_NS = 10h` — a deliberate operator bound
   (`R8_OPERATOR_RUNBOOK.md:138,178-181`), pinned by
   `test_the_permit_ttl_is_pinned_to_ten_hours`. Boot 16:50Z ⇒ expiry 02:50Z;
   mid-day window closes 01:00Z; next LAUNCH 16:40Z.
   **CORRECTION to an earlier statement of mine:** this is NOT "structurally
   undetectable". `parse_permit_expiry_ns` is called at THREE sites
   (`trade_supervisor.py:1027`, `:1112`, `:1228`); only the
   `permit_expiry_valid` COMPARISON is self-check-only, and `core:544`
   already folds it into `FAIL_SHADOW_MODE_NO_PERMIT`. The accurate form is:
   **detected once, at a time when it is trivially true, and only ever at
   WARN.** The expiry is already latched by the mid-day loop, so the fix is a
   comparison, not new plumbing.

## 1. Work packages

| id | title | size | depends | acceptance test | abandonment criterion |
|---|---|---|---|---|---|
| **A0** | Fee-drift evidence pack: is θ=0.0695 persistent, universal, taker-only? Re-pull `feeCoefficient` across all listed weather slugs ≥5 consecutive days; separate wire drift from tape-writer artefact; record the maker field independently | S | — | Dated doc under `docs/evidence/venue/polymarket_us/` with per-slug/per-day θ; RED-first test pinning the OBSERVED SET (extends `test_polymarket_us_fee_schedule_pin.py`) failing against the current single-value pin. **No `src/` constant change.** | θ non-stationary (≥2 distinct values in a week) ⇒ the family cannot be re-registered against a moving cost basis ⇒ A1 forced to RETIRE or HALT |
| **A1** | **The θ ruling — a DECISION, not a constant edit.** Options: (i) RETIRE v3; (ii) **STOP TRADING THIS SURFACE**; (iii) re-register class-C `pm_us_crh_v4` at observed θ, **n reset to 0 per L-34**, new `d0_climate_day`, new `trial_id_prefix`, fresh LD-OBF α | M | A0 | Signed ruling doc; if (iii) a new `family_manifest` + RED-first `assert_family_only` proving v3 rows are REFUSED into the v4 tally; if (i)/(ii) a `family_halted` state + test that the node refuses to arm it | **Precondition for (iii):** a post-θ edge estimate whose CI excludes 0. Fact 1 shows the model ranked 1.98× worse and higher θ raises the bar, so if A0 cannot produce one, **(iii) is abandoned by default and (ii) is the answer** |
| **B1** | **Permit-lapse detector (CAPABILITY assertion).** `permit_capability_valid(state, now_ns)` in `trade_supervisor_core.py`; due on EVERY poll while a child is adopted. CRITICAL `TRADE_SUPERVISOR_PERMIT_LAPSED` + repeating heartbeat. Fail-closed | S–M | — | RED-first: fake clock 16:50Z→03:00Z, healthy child that never re-mints; ≥1 CRITICAL at first lapse and a repeat at heartbeat. **Must also assert the alert fires with `midday_alert_sent` latched** (see risk 3). TTL pin test unchanged and green; a fresh test asserts the ONE-caller mint barrier | Not a hypothesis. Tripwire: if it cannot alert without a second mint site, ESCALATE — never extend the TTL |
| **B2** | Strategy-side defence in depth: gate becomes `permit is not None and clock.timestamp_ns() <= permit.expires_at_ns`, refusal counted through the named refusal path so a lapse is VISIBLE, not a silent no-op | S | B1 | RED-first, two tests per strategy: expired permit refuses AND increments a named counter; valid permit byte-identical. `safety.py:986` chokepoint test untouched and green | — |
| **B3** | Operational posture: is the 02:50Z→16:40Z impotent window (a) accepted and merely alerted, or (b) closed by moving LAUNCH later / a second intraday process under the existing one-process-per-day flock? | S | B1 | `R8_OPERATOR_RUNBOOK.md` states the posture WITH the arithmetic; supervisor test asserts the alert fires under it | — |
| **C0** | **Measure the real WS subscription cap BEFORE sizing anything.** The cap may count `requestId`s, not slugs. Probe: 1 connection / 1 MARKET_DATA requestId carrying 30 slugs; then 10 requestIds × 1 slug; record which is refused | S | — | Venue-evidence doc with the refusal boundary and raw frames. Zero orders, zero exposure | If both shapes refuse above 10 SLUGS, C1's connection fan-out is mandatory; if requestIds are the unit, C1 collapses to a slug-list change |
| **C1** | **NO-leg depth capture.** Subscribe the live `^no` subset to `order_book_depths` alongside YES. Connection sizing per C0. Idle-timeout (60 s without a frame closes the socket) re-tested per added connection — a thin NO book idles more readily than YES | M–L | C0 | RED-first: recorder test asserting `^no` ids reach `subscribe_order_book_depth`; integration acceptance that after one live session `order_book_depths` holds ≥1 `^no` dir with L0 bid AND ask. Catalog-root disjointness still enforced. No new analysis code | **21 days** of capture if qualifying events accrue at < 0.25/station-day (n≈30 then >8 weeks away) |
| **C2** | Readout of the frozen region (registered in `WP7b_MARKET_AS_FORECASTER_2026-09-20.md`). Runs only at n ≥ 30. **UNARMED** — shadow valuation at the actually-quoted NO ask | M | C1 | Station-day-clustered 95% CI on realised NO-leg PnL. **Arms nothing by itself** | CI includes 0, or lower bound ≤ 0 ⇒ hypothesis CLOSED; with A1(ii) that ends the PM.us programme |

**Folded on arrival:** `PREREG_v5_crh_rest` → `CLOSED_NOT_REGISTERED`.

## 2. Critical path

`B1 → B2 → B3` is unconditional and lands FIRST. It delivers *"we would know if
it stopped"* regardless of the A ruling — and a bot restored by A1(iii) into an
undetected permit lapse is worse than a halted one.

`A0 → A1` is the *"trade again"* half. Its honest expected outcome is **(ii)
stop trading this surface**: three hypotheses are dead, the survivor is
unmeasurable, and θ moved against us.

`C` is the only path that could re-open the surface: ~3 weeks of pure capture,
zero exposure.

**Nothing arms.** Arming requires A1(iii) AND a C2 CI strictly > 0 AND an
operator budget ceiling — the last is operator-only and is never valued in code.

## 3. Top risks

1. **The WS cap is misread as per-slug when it is per-`requestId`.** The SDK's
   `BaseWebSocket.subscribe(request_id, subscription_type, market_slugs: list[str])`
   carries an arbitrary slug list. If the cap counts SUBSCRIPTIONS, 60
   instruments is 2 requestIds on 1 connection and C1's central design question
   evaporates. **Falsified by C0. Do not design fan-out before running it.**
2. **A1 re-registers by momentum.** The plan's own gravity is "resume".
   Falsified by requiring the A0 post-θ edge estimate BEFORE the ruling, with
   (ii) as the stated default.
3. **The permit detector is silenced by an unrelated latch.**
   `trade_supervisor.py:1104` returns on `state.midday_alert_sent` BEFORE any
   log read, so one exhausted mid-day relaunch budget would mute permit
   alerting for the rest of the day. **Falsified by** a B1 test that latches
   `midday_alert_sent` and still asserts the CRITICAL fires.

## 4. Binding constraints

Nautilus IMMUTABLE (native extension points only; `Actor`, `set_timer`,
`register_arrow`, catalog). `allow_short` stays `False`. No safety/settlement/
contract test weakened. Operator caps never valued in code. No real-money
exposure to validate any hypothesis. No `dataclasses.asdict`/`astuple`. Every
hypothesis WP carries a pre-registered abandonment criterion.
